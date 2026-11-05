-- GIIC — Esquema Supabase (PostgreSQL) con Row Level Security.
-- Ejecutar en Supabase: SQL Editor → pegar → Run. Idempotente (IF NOT EXISTS).
--
-- Privacidad: la cartera y los ajustes son PRIVADOS por usuario (auth.uid()).
-- Los datos de mercado y los snapshots del scanner son legibles por cualquier
-- usuario autenticado, pero SOLO el job (service_role, que omite RLS) puede
-- escribirlos. La service_role key nunca va al navegador ni al repositorio.

-- ----------------------------------------------------------------------------
-- DATOS PRIVADOS DEL USUARIO
-- ----------------------------------------------------------------------------
create table if not exists public.positions (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  ticker      text not null,
  name        text default '',
  asset_class text not null default 'equity',
  sector      text,
  country     text default 'US',
  currency    text not null default 'USD',
  quantity    numeric not null check (quantity > 0),
  avg_cost    numeric not null check (avg_cost >= 0),
  opened_at   date,
  created_at  timestamptz not null default now()
);

create table if not exists public.settings (
  user_id              uuid primary key default auth.uid() references auth.users(id) on delete cascade,
  base_currency        text not null default 'USD',
  capital_available    numeric not null default 0,
  monthly_contribution numeric not null default 0,
  risk_tolerance       text not null default 'moderate',
  horizon_years        numeric not null default 15,
  max_weight_per_asset numeric not null default 0.25,
  max_weight_per_sector numeric not null default 0.40,
  min_cash             numeric not null default 0
);

-- ----------------------------------------------------------------------------
-- DATOS DE MERCADO (compartidos, solo lectura para usuarios; escribe el job)
-- ----------------------------------------------------------------------------
create table if not exists public.prices (
  ticker     text primary key,
  close      numeric not null,
  as_of      date not null,
  currency   text not null default 'USD',
  updated_at timestamptz not null default now()
);

create table if not exists public.fundamentals (
  ticker     text primary key,
  payload    jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists public.etf_holdings (
  etf    text not null,
  ticker text not null,
  weight numeric not null,
  name   text,
  primary key (etf, ticker)
);

create table if not exists public.fx_rates (
  currency text primary key,     -- moneda origen
  base     text not null,        -- moneda base
  rate     numeric not null,     -- unidades de base por 1 unidad de origen
  as_of    date not null
);

-- ----------------------------------------------------------------------------
-- RESULTADOS DEL SCANNER (point-in-time, para futuro backtesting)
-- ----------------------------------------------------------------------------
create table if not exists public.scan_runs (
  id                         uuid primary key,
  as_of                      date not null,
  created_at                 timestamptz not null default now(),
  status                     text not null default 'pending',  -- pending | completed | failed
  completed_at               timestamptz,
  error                      text,
  universe_version           text not null,
  algo_version               text not null,
  evaluated                  int not null default 0,
  using_sample_data          boolean not null default false,
  coverage                   jsonb,
  usable_factors             jsonb,
  excluded_insufficient_data jsonb,
  stale_excluded             jsonb,
  fresh_fraction             numeric,
  weights                    jsonb
);

create table if not exists public.scan_snapshots (
  run_id           uuid not null references public.scan_runs(id) on delete cascade,
  ticker           text not null,
  as_of            date not null,
  universe_version text not null,
  algo_version     text not null,
  rank             int not null,
  composite        numeric,
  factor_value     numeric,
  factor_quality   numeric,
  factor_growth    numeric,
  factor_momentum  numeric,
  factor_low_risk  numeric,
  tags             jsonb,
  sector           text,
  is_sample        boolean not null default false,
  primary key (run_id, ticker)
);
create index if not exists idx_snapshots_asof on public.scan_snapshots (as_of desc, rank asc);

-- Vista: snapshots de la corrida COMPLETADA más reciente (publicación atómica).
-- Una corrida 'pending' o 'failed' nunca aparece aquí, así el frontend jamás ve
-- datos a medias. Respeta RLS con security_invoker.
create or replace view public.v_latest_scan with (security_invoker = on) as
  select s.*
  from public.scan_snapshots s
  join (
    select id from public.scan_runs
    where status = 'completed'
    order by completed_at desc nulls last, created_at desc
    limit 1
  ) r on s.run_id = r.id
  order by s.rank asc;

-- ----------------------------------------------------------------------------
-- ROW LEVEL SECURITY
-- ----------------------------------------------------------------------------
alter table public.positions      enable row level security;
alter table public.settings       enable row level security;
alter table public.prices         enable row level security;
alter table public.fundamentals   enable row level security;
alter table public.etf_holdings   enable row level security;
alter table public.fx_rates       enable row level security;
alter table public.scan_runs      enable row level security;
alter table public.scan_snapshots enable row level security;

-- Privadas: el dueño hace todo sobre sus filas.
drop policy if exists positions_owner on public.positions;
create policy positions_owner on public.positions
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists settings_owner on public.settings;
create policy settings_owner on public.settings
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Mercado/scanner: lectura para autenticados; la escritura la hace service_role
-- (omite RLS), por lo que no se define ninguna policy de escritura.
do $$
declare t text;
begin
  foreach t in array array['prices','fundamentals','etf_holdings','fx_rates','scan_runs','scan_snapshots']
  loop
    execute format('drop policy if exists %I_read on public.%I', t, t);
    execute format('create policy %I_read on public.%I for select to authenticated using (true)', t, t);
  end loop;
end $$;
