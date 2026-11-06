-- 0010_etf_holdings_xray.sql — Portfolio X-Ray. ADITIVA. PENDIENTE DE APROBACIÓN: no ejecutar.
-- Ajustes finales: (1) elimina SOLO la UNIQUE antigua (etf,ticker) si existe; (2) clave de
-- snapshot con identificadores OBLIGATORIOS + validaciones; (3) tabla de calidad de snapshot.

-- ticker NULLABLE (efectivo/derivados/sin ticker).
alter table public.etf_holdings alter column ticker drop not null;

alter table public.etf_holdings
  add column if not exists provider     text,
  add column if not exists as_of        date,
  add column if not exists captured_at  timestamptz not null default now(),
  add column if not exists name         text,
  add column if not exists cusip        text,
  add column if not exists isin         text,
  add column if not exists figi         text,
  add column if not exists share_class  text,
  add column if not exists company_key  text,          -- id de EMPRESA (emisor) para consolidar
  add column if not exists asset_class  text not null default 'equity',
  add column if not exists market_value numeric,        -- valor de mercado de la línea
  add column if not exists notional     numeric,        -- exposición económica (derivados), si existe
  add column if not exists line_key     text;           -- clave estable de la línea

-- (1) Eliminar EXCLUSIVAMENTE la UNIQUE antigua cuyas columnas sean exactamente (etf,ticker).
do $$
declare r record;
begin
  for r in
    select con.conname from pg_constraint con
    where con.conrelid = 'public.etf_holdings'::regclass and con.contype = 'u'
      and (select array_agg(att.attname order by att.attname)
             from unnest(con.conkey) k
             join pg_attribute att on att.attrelid = con.conrelid and att.attnum = k)
          = array['etf','ticker']
  loop
    execute format('alter table public.etf_holdings drop constraint %I', r.conname);
  end loop;
end $$;

-- (2) Identificadores de snapshot OBLIGATORIOS (tabla vacía: seguro) -> unicidad real sin NULL.
alter table public.etf_holdings alter column provider set not null;
alter table public.etf_holdings alter column as_of    set not null;
alter table public.etf_holdings alter column line_key set not null;

-- Validaciones (no limitan pesos: ETFs apalancados/derivados pueden ser negativos o >1).
alter table public.etf_holdings
  add constraint etf_holdings_weight_finite
    check (weight is null or weight::text not in ('NaN','Infinity','-Infinity')),
  add constraint etf_holdings_asof_valid   check (as_of >= date '1990-01-01'),
  add constraint etf_holdings_line_key_ne  check (length(line_key) > 0),
  add constraint etf_holdings_provider_ne  check (length(provider) > 0),
  add constraint etf_holdings_class_valid
    check (asset_class in ('equity','cash','derivative','bond','fx','other','unidentified'));
-- Unidad de weight: FRACCIÓN del fondo (0.07 = 7%). La validez del rango futuro de as_of
-- se controla en la aplicación (current_date no es inmutable para un CHECK).

create unique index if not exists etf_holdings_snapshot
  on public.etf_holdings (etf, provider, as_of, line_key);
create index if not exists etf_holdings_company on public.etf_holdings (company_key);
create index if not exists etf_holdings_latest  on public.etf_holdings (etf, as_of desc);

-- (3) Calidad de snapshot: estado y cobertura por (etf, proveedor, fecha). El X-Ray usa el
-- último snapshot 'complete'; 'partial'/'failed' quedan registrados pero NO reemplazan al
-- último válido. 'stale' marca desactualización.
create table if not exists public.etf_snapshots (
  id          uuid primary key default gen_random_uuid(),
  etf         text not null,
  provider    text not null,
  as_of       date not null,
  status      text not null check (status in ('complete','partial','failed','stale')),
  n_lines     integer,
  weight_sum  numeric,     -- Σ de pesos (diagnóstico de cobertura; equity+otros)
  equity_pct  numeric,     -- fracción identificada como equity
  captured_at timestamptz not null default now(),
  note        text,
  unique (etf, provider, as_of)
);

-- RLS: lectura autenticada (dato de mercado); escritura solo service role (jobs).
alter table public.etf_holdings enable row level security;
alter table public.etf_snapshots enable row level security;
drop policy if exists etf_holdings_read on public.etf_holdings;
create policy etf_holdings_read on public.etf_holdings for select to authenticated using (true);
drop policy if exists etf_snapshots_read on public.etf_snapshots;
create policy etf_snapshots_read on public.etf_snapshots for select to authenticated using (true);
revoke insert, update, delete on public.etf_holdings  from anon, authenticated;
revoke insert, update, delete on public.etf_snapshots from anon, authenticated;
