-- 0009_fintual_funds.sql — Soporte de fondos Fintual México (ingreso manual).
-- ADITIVA. No toca predictions ni tablas existentes. RLS por usuario (aislamiento).
-- PENDIENTE DE APROBACIÓN: no ejecutar hasta visto bueno de Pablo.
--
-- Diseño:
--  - user_funds: catálogo per-usuario de fondos que el usuario incorpora (Fintual u otros).
--  - fund_navs : historial de valor cuota (NAV) ingresado MANUALMENTE por el usuario, fechado.
--  Los FLUJOS (aportación/retiro/compra/venta de participaciones) se registran en la tabla
--  EXISTENTE `transactions` usando `ticker` = símbolo del fondo (p. ej. 'FINTUAL:RISK').
--  La valorización = participaciones × NAV más reciente (<= fecha) × tipo de cambio (fx_rates).

create table if not exists public.user_funds (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  symbol      text not null,                 -- identificador estable del fondo (no reciclable)
  name        text,
  provider    text not null default 'fintual',
  currency    text not null default 'MXN',
  created_at  timestamptz not null default now(),
  unique (user_id, symbol)
);

create table if not exists public.fund_navs (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  symbol      text not null,
  as_of       date not null,
  nav         numeric not null check (nav > 0),  -- valor cuota
  currency    text not null default 'MXN',
  source      text not null default 'manual',    -- 'manual' | 'import' | 'api' (futuro)
  created_at  timestamptz not null default now(),
  unique (user_id, symbol, as_of)
);

-- RLS: cada usuario solo ve y escribe lo suyo (igual que `transactions`).
alter table public.user_funds enable row level security;
alter table public.fund_navs  enable row level security;

drop policy if exists user_funds_owner on public.user_funds;
create policy user_funds_owner on public.user_funds
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists fund_navs_owner on public.fund_navs;
create policy fund_navs_owner on public.fund_navs
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create index if not exists fund_navs_symbol_date on public.fund_navs (user_id, symbol, as_of desc);
