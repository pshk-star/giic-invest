-- 0009_fintual_funds.sql — Soporte de fondos Fintual México (ingreso manual).
-- ADITIVA. No toca predictions. RLS por usuario. PENDIENTE DE APROBACIÓN: no ejecutar.
--
-- Identidad ESTABLE del fondo = user_funds.id (uuid, fund_id). El símbolo puede cambiar
-- (Fintual puede renombrar); por eso NAV y transacciones referencian fund_id, NO el símbolo.
-- external_id guarda el identificador del proveedor (estable) para evitar duplicados al
-- re-incorporar un fondo. Los FLUJOS se registran en la tabla EXISTENTE `transactions`
-- añadiéndole una columna fund_id: si fund_id es NOT NULL -> es un fondo; si es NULL -> es
-- acción/ETF como hasta ahora (compatibilidad total, filas existentes intactas).

-- 1) Catálogo de fondos por usuario (fund_id estable).
create table if not exists public.user_funds (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null default auth.uid() references auth.users(id) on delete cascade,
  symbol       text not null,                         -- símbolo actual (mutable), p. ej. 'FINTUAL-RISK'
  external_id  text,                                  -- id estable del proveedor (si existe)
  name         text,
  provider     text not null default 'fintual',
  currency     text not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  created_at   timestamptz not null default now(),
  unique (user_id, symbol),                           -- lookup por símbolo actual
  unique (user_id, provider, external_id)             -- evita duplicar el mismo fondo del proveedor
);

-- 2) NAV (valor cuota) manual y fechado, referenciando fund_id (no símbolo).
create table if not exists public.fund_navs (
  id        uuid primary key default gen_random_uuid(),
  user_id   uuid not null default auth.uid() references auth.users(id) on delete cascade,
  fund_id   uuid not null references public.user_funds(id) on delete cascade,
  as_of     date not null,
  nav       numeric not null check (nav > 0),         -- valor cuota en la moneda del fondo
  currency  text not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  source    text not null default 'manual',           -- 'manual' | 'import' | 'api' (futuro)
  created_at timestamptz not null default now(),
  unique (fund_id, as_of)                             -- un NAV por fondo y fecha (idempotente)
);

-- 3) Enlace con transacciones existentes: columna fund_id NULLABLE (acción/ETF = NULL).
alter table public.transactions
  add column if not exists fund_id uuid references public.user_funds(id) on delete set null;

-- RLS: aislamiento por usuario (mismo patrón que `transactions`).
alter table public.user_funds enable row level security;
alter table public.fund_navs  enable row level security;

drop policy if exists user_funds_owner on public.user_funds;
create policy user_funds_owner on public.user_funds
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists fund_navs_owner on public.fund_navs;
create policy fund_navs_owner on public.fund_navs
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create index if not exists fund_navs_fund_date on public.fund_navs (fund_id, as_of desc);
create index if not exists transactions_fund    on public.transactions (fund_id) where fund_id is not null;

-- Compatibilidad / no duplicación (convención de aplicación, documentada):
--   * Aportación que compra participaciones -> 1 fila transactions: side='buy', fund_id=<fondo>,
--     quantity=participaciones, price=NAV de compra, currency=moneda del fondo.
--   * Retiro -> side='sell', fund_id=<fondo>, quantity=participaciones vendidas.
--   * Depósito/retiro de EFECTIVO no invertido -> side='deposit'/'withdrawal' (fund_id NULL),
--     NO cuenta como movimiento del fondo (evita doble conteo).
--   * Valorización del fondo = Σ(participaciones) × NAV más reciente (<= fecha) × FX(moneda->base).
--   * Diferenciación en cartera: fund_id NOT NULL => fondo (valora con fund_navs); NULL => acción/ETF
--     (valora con quotes/price_history). Nunca ambas vías para el mismo capital.
