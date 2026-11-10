-- P1.9 — Valoración fundamental (EXPERIMENTAL). Tabla ADITIVA; no toca el Fair Value productivo
-- ni Advisor. El frontend la lee bajo feature flag y solo la renderiza. Un registro por ticker
-- (upsert por ticker): el payload JSONB lo calcula app/jobs/fundamental_valuation.py (única fuente
-- de lógica financiera).
create table if not exists public.fundamental_valuation (
  ticker       text primary key,
  as_of        date not null,
  payload      jsonb not null,
  generated_at timestamptz not null default now()
);

comment on table public.fundamental_valuation is
  'P1.9 experimental: valoración fundamental multi-modelo (DCF productivo, FCFF GIIC, corregido, combinado). No productiva, no recomendación.';

-- Solo lectura para autenticados (como el resto del scanner); escritura por service role (job).
alter table public.fundamental_valuation enable row level security;
do $$ begin
  create policy fundamental_valuation_read on public.fundamental_valuation
    for select using (auth.role() = 'authenticated');
exception when duplicate_object then null; end $$;
