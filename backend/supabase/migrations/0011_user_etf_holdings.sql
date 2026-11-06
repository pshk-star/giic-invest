-- 0011_user_etf_holdings.sql — Importación MANUAL de holdings oficiales por usuario (CSV/XLSX).
-- ADITIVA. RLS por usuario. PENDIENTE DE APROBACIÓN: no ejecutar.
-- Control de integridad por importación: cada archivo genera un SNAPSHOT con estado
-- (complete/partial/failed), fecha de composición, nº de líneas y suma de pesos. El X-Ray
-- usa SOLO importaciones 'complete'; una parcial/fallida nunca reemplaza la última válida.

-- Líneas de holdings importadas.
create table if not exists public.user_etf_holdings (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  etf         text not null,
  as_of       date not null check (as_of >= date '1990-01-01'),
  provider    text not null default 'manual',
  source_file text,
  ticker      text,
  name        text,
  cusip       text,
  company_key text,
  sector      text,
  asset_class text not null default 'equity'
    check (asset_class in ('equity','cash','derivative','bond','fx','commodity','other','unidentified')),
  weight      numeric check (weight is null or weight::text not in ('NaN','Infinity','-Infinity')),
  line_key    text not null check (length(line_key) > 0),
  captured_at timestamptz not null default now(),
  unique (user_id, etf, as_of, line_key)   -- idempotencia: no duplica al reimportar el mismo archivo
);

-- Metadatos/estado de cada importación (una por etf+fecha de composición).
create table if not exists public.user_etf_imports (
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  etf         text not null,
  as_of       date not null check (as_of >= date '1990-01-01'),
  status      text not null check (status in ('complete','partial','failed')),
  n_lines     integer not null default 0,
  weight_sum  numeric,
  source_file text,
  captured_at timestamptz not null default now(),
  primary key (user_id, etf, as_of)
);

alter table public.user_etf_holdings enable row level security;
alter table public.user_etf_imports  enable row level security;

drop policy if exists user_etf_holdings_owner on public.user_etf_holdings;
create policy user_etf_holdings_owner on public.user_etf_holdings
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists user_etf_imports_owner on public.user_etf_imports;
create policy user_etf_imports_owner on public.user_etf_imports
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create index if not exists user_etf_holdings_lookup on public.user_etf_holdings (user_id, etf, as_of desc);
create index if not exists user_etf_imports_lookup  on public.user_etf_imports  (user_id, etf, status, as_of desc);
