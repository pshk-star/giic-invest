-- 0008_pit_sources.sql — Base histórica MULTIFUENTE y point-in-time. ADITIVA e IDEMPOTENTE.
-- Agnóstica de proveedor (hoy EDGAR/FRED/Yahoo; mañana proveedores de pago sin rehacer el
-- motor). Requiere 0007 (reutiliza prevent_mutation). NO ejecutar sin autorización.
--
-- Ajustes de esta versión final (feedback):
--  (1) fundamentals_pit: identificadores ESTABLES de SEC (cik, accession) + form_type,
--      context_ref, taxonomy, unit => sin colisiones entre filings del mismo día; la
--      unicidad es por documento estable + hecho, no por fecha.
--  (2) macro_pit: índices y CHECK para que las consultas respeten vintages y disponibilidad
--      real; regla PIT documentada (valor conocido en D = mayor vintage con vintage<=D y
--      release_date<=D).
--  (3) data_coverage: distingue TENER el esquema de TENER cobertura real (deslistados,
--      membresías). Se registra explícitamente qué está realmente cargado y si es completo.
--  (4) price_adjustment_lineage: snapshot_id + actions_hash para que cada backtest
--      reconstruya EXACTAMENTE la versión de precios usada (referenciada en predictions.data_ref).
--  (5) Constraints, índices, inmutabilidad y pruebas (0008_selftest.sql); compatible con 0004/0006/0007.

-- Maestro de instrumentos (incluye deslistados y ADR extranjeros).
create table if not exists public.securities (
  figi          text,
  ticker        text not null,
  cik           text,                               -- id SEC del emisor (estable)
  name          text,
  status        text not null default 'active',     -- 'active'|'delisted'
  is_adr        boolean not null default false,
  home_country  text,
  first_date    date,
  last_date     date,
  provider      text not null default 'yahoo',
  updated_at    timestamptz not null default now(),
  primary key (provider, ticker)
);

-- Pertenencia histórica a índices (contra sesgo de supervivencia).
create table if not exists public.index_membership (
  index_code text not null,
  ticker     text not null,
  start_date date not null,
  end_date   date,
  provider   text not null,
  unique (index_code, ticker, start_date, provider)
);

-- (3) Cobertura real de datos: TENER esquema != TENER historia. Se registra lo cargado.
create table if not exists public.data_coverage (
  dataset     text not null,          -- 'index_membership:SP500','securities:delisted','fundamentals_pit:MU',...
  provider    text not null,
  as_of       date not null,
  is_complete boolean not null default false,
  n_rows      bigint,
  note        text,
  updated_at  timestamptz not null default now(),
  primary key (dataset, provider)
);

-- (1) Fundamentales POINT-IN-TIME con identificadores estables.
create table if not exists public.fundamentals_pit (
  id            bigint generated always as identity primary key,
  provider      text not null,                  -- 'edgar' | <proveedor de pago>
  cik           text,                           -- emisor estable (SEC)
  ticker        text not null,
  accession     text,                           -- id ESTABLE del documento SEC (filing)
  form_type     text,                           -- '10-K','10-Q','10-K/A',...
  concept       text not null,                  -- tag (us-gaap:Revenues, ...)
  context_ref   text not null default '',       -- contexto XBRL (periodo/dimensión)
  unit          text not null default '',       -- 'USD','USD/shares','shares',...
  taxonomy      text,                           -- p.ej. 'us-gaap/2025'
  period_start  date,
  period_end    date not null,
  fiscal_period text,                           -- 'FY2025','Q3-2025'
  value         numeric,
  filing_date   date not null,                  -- DISPONIBILIDAD real (publicación)
  amended       boolean not null default false, -- true si reexpresa un periodo ya reportado
  source_doc    text,
  retrieved_at  timestamptz not null default now(),
  ingest_run_id text,
  -- Unicidad por documento ESTABLE + hecho => dos filings del MISMO día no colisionan
  -- (distinto accession); reexpresiones posteriores = distinto accession = fila nueva.
  unique (provider, accession, concept, context_ref, unit)
);
create index if not exists fundamentals_pit_pit_lookup
  on public.fundamentals_pit (ticker, concept, period_end, filing_date);
create index if not exists fundamentals_pit_asof
  on public.fundamentals_pit (ticker, filing_date);

-- (2) Series macro con vintages. Consulta PIT: valor conocido en D = el de MAYOR vintage
-- con vintage <= D y release_date <= D (nunca usar una revisión futura en backtests).
create table if not exists public.macro_pit (
  id            bigint generated always as identity primary key,
  provider      text not null default 'fred',    -- 'fred'/'alfred' | <proveedor de pago>
  series_id     text not null,
  obs_date      date not null,                    -- fecha del dato observado
  value         numeric,
  release_date  date,                             -- disponibilidad pública
  vintage       date not null,                    -- versión (ALFRED); PIT
  revision      integer,
  retrieved_at  timestamptz not null default now(),
  unique (provider, series_id, obs_date, vintage)
);
create index if not exists macro_pit_vintage on public.macro_pit (series_id, obs_date, vintage desc);
create index if not exists macro_pit_release on public.macro_pit (series_id, release_date);
do $$ begin
  if not exists (select 1 from pg_constraint where conname='macro_pit_release_after_obs_chk') then
    alter table public.macro_pit add constraint macro_pit_release_after_obs_chk
      check (release_date is null or release_date >= obs_date) not valid;
  end if;
end $$;

-- (4) Linaje de ajuste de precios: cada backtest referencia el snapshot_id usado y puede
-- reconstruir EXACTAMENTE el adjclose (adjusted_through + hash del set de corporate_actions).
create table if not exists public.price_adjustment_lineage (
  id                bigint generated always as identity primary key,
  snapshot_id       text not null,            -- versión de precios usada (referida en predictions.data_ref)
  ticker            text not null,
  adjusted_through  date not null,            -- hasta qué fecha incorpora splits/dividendos
  actions_hash      text,                     -- hash del conjunto de corporate_actions aplicadas
  n_actions         integer,
  adjustment_source text not null default 'yahoo',
  captured_at       timestamptz not null default now(),
  unique (snapshot_id, ticker)
);
create index if not exists price_adj_lineage_ticker on public.price_adjustment_lineage (ticker, adjusted_through);

-- RLS: lectura autenticada; escritura solo service role; sin INSERT/UPDATE/DELETE a anon/auth.
do $$ declare t text; begin
  foreach t in array array['securities','index_membership','data_coverage','fundamentals_pit','macro_pit','price_adjustment_lineage'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I_read on public.%I', t, t);
    execute format('create policy %I_read on public.%I for select to authenticated using (true)', t, t);
    execute format('revoke insert, update, delete on public.%I from anon, authenticated', t);
  end loop;
end $$;

-- Inmutabilidad (append-only) para las PIT: fundamentals_pit, macro_pit, price_adjustment_lineage.
-- securities, index_membership y data_coverage SÍ admiten actualización (estado/cobertura cambian).
do $$ begin
  if exists (select 1 from pg_proc where proname='prevent_mutation') then
    drop trigger if exists fundamentals_pit_append_only on public.fundamentals_pit;
    create trigger fundamentals_pit_append_only before update or delete on public.fundamentals_pit
      for each row execute function public.prevent_mutation();
    drop trigger if exists macro_pit_append_only on public.macro_pit;
    create trigger macro_pit_append_only before update or delete on public.macro_pit
      for each row execute function public.prevent_mutation();
    drop trigger if exists price_adj_lineage_append_only on public.price_adjustment_lineage;
    create trigger price_adj_lineage_append_only before update or delete on public.price_adjustment_lineage
      for each row execute function public.prevent_mutation();
  end if;
end $$;
