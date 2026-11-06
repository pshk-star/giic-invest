-- 0008_pit_sources.sql — Base histórica MULTIFUENTE y point-in-time. ADITIVA e IDEMPOTENTE.
-- Diseñada para ser AGNÓSTICA de proveedor: hoy EDGAR/FRED/Yahoo (gratis); mañana
-- proveedores de PAGO sin rehacer el motor (el modelo consume estas tablas, no al proveedor).
-- NO ejecutar sin autorización.
--
-- Atiende explícitamente:
--  - Datos financieros corregidos/republicados tras el filing original: cada reexpresión
--    es una FILA NUEVA (clave incluye filing_date+provider); nunca se sobrescribe.
--  - Fecha REAL de disponibilidad: filing_date (fundamentales) / release_date (macro).
--  - Vintages macro (ALFRED): clave incluye vintage; cada revisión es otra fila.
--  - Empresas deslistadas y sesgo de supervivencia: securities (status) + index_membership
--    (pertenencia histórica con fechas) para reconstruir universos point-in-time.
--  - Emisores extranjeros (TSM, ASML): securities.is_adr / home_country.
--  - Ajustes retroactivos por splits/dividendos: se registran en corporate_actions (0004);
--    price_history guarda cierre AJUSTADO (adjusted=true). La reproducibilidad del ajuste
--    se documenta por adjustment_source (abajo, en price_adjustment_lineage).

-- Maestro de instrumentos (incluye deslistados y ADR extranjeros).
create table if not exists public.securities (
  figi          text,                 -- id estable si el proveedor lo da (evita colisión por reasignación de ticker)
  ticker        text not null,
  name          text,
  status        text not null default 'active',   -- 'active'|'delisted'
  is_adr        boolean not null default false,
  home_country  text,
  first_date    date,
  last_date     date,                  -- fecha de deslistado si aplica
  provider      text not null default 'yahoo',
  updated_at    timestamptz not null default now(),
  primary key (provider, ticker)
);

-- Pertenencia histórica a índices/universos (clave contra sesgo de supervivencia).
create table if not exists public.index_membership (
  index_code text not null,            -- p.ej. 'SP500','NDX'
  ticker     text not null,
  start_date date not null,
  end_date   date,                     -- null = aún miembro
  provider   text not null,
  unique (index_code, ticker, start_date, provider)
);

-- Fundamentales POINT-IN-TIME. Cada (concepto, periodo, filing, proveedor) es una fila;
-- las reexpresiones posteriores entran como filas nuevas (amended=true).
create table if not exists public.fundamentals_pit (
  id            bigint generated always as identity primary key,
  provider      text not null,                 -- 'edgar' | <proveedor de pago>
  ticker        text not null,
  concept       text not null,                 -- 'revenue','eps_diluted','fcf','net_margin',...
  period_end    date not null,                 -- fin del periodo fiscal al que se refiere
  fiscal_period text,                           -- 'FY2025','Q3-2025'
  value         numeric,
  unit          text,
  filing_date   date not null,                  -- DISPONIBILIDAD real (fecha de publicación)
  amended       boolean not null default false, -- true si reexpresa un periodo ya reportado
  source_doc    text,                           -- accession/URL del documento
  retrieved_at  timestamptz not null default now(),
  ingest_run_id text,
  unique (provider, ticker, concept, period_end, filing_date)
);
create index if not exists fundamentals_pit_lookup on public.fundamentals_pit (ticker, concept, period_end, filing_date);

-- Series macro con vintages (revisiones): cada vintage es una fila.
create table if not exists public.macro_pit (
  id            bigint generated always as identity primary key,
  provider      text not null default 'fred',   -- 'fred'/'alfred' | <proveedor de pago>
  series_id     text not null,                   -- 'CPIAUCSL','DGS10','UNRATE',...
  obs_date      date not null,                   -- fecha del dato observado
  value         numeric,
  release_date  date,                            -- cuándo se publicó (disponibilidad)
  vintage       date not null,                   -- fecha de la versión (ALFRED); PIT
  revision      integer,
  retrieved_at  timestamptz not null default now(),
  unique (provider, series_id, obs_date, vintage)
);
create index if not exists macro_pit_lookup on public.macro_pit (series_id, obs_date, vintage);

-- Linaje del ajuste de precios (reproducibilidad del adjclose).
create table if not exists public.price_adjustment_lineage (
  id                bigint generated always as identity primary key,
  ticker            text not null,
  adjusted_through  date not null,       -- hasta qué fecha incorpora splits/dividendos
  adjustment_source text not null default 'yahoo',
  captured_at       timestamptz not null default now()
);

-- RLS: lectura autenticada; escritura solo service role (sin policy de escritura).
do $$ declare t text; begin
  foreach t in array array['securities','index_membership','fundamentals_pit','macro_pit','price_adjustment_lineage'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists %I_read on public.%I', t, t);
    execute format('create policy %I_read on public.%I for select to authenticated using (true)', t, t);
  end loop;
end $$;

-- Append-only para las PIT inmutables (reutiliza prevent_mutation de 0007).
do $$ begin
  if exists (select 1 from pg_proc where proname='prevent_mutation') then
    drop trigger if exists fundamentals_pit_append_only on public.fundamentals_pit;
    create trigger fundamentals_pit_append_only before update or delete on public.fundamentals_pit
      for each row execute function public.prevent_mutation();
    drop trigger if exists macro_pit_append_only on public.macro_pit;
    create trigger macro_pit_append_only before update or delete on public.macro_pit
      for each row execute function public.prevent_mutation();
  end if;
end $$;
-- Nota: securities e index_membership SÍ admiten actualización (estado/último día cambian);
-- fundamentals_pit y macro_pit son inmutables (las correcciones entran como filas nuevas).
