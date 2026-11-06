-- 0009_fintual_funds.sql — Soporte de fondos Fintual México (ingreso manual).
-- ADITIVA. No toca predictions. RLS por usuario. PENDIENTE DE EJECUCIÓN EN SUPABASE.
--
-- Precauciones (aprobadas):
--  (1) SIN pérdida de historial: NAV y transacciones de fondos usan ON DELETE RESTRICT
--      (no se puede borrar un fondo con historial). Para "quitar" un fondo se ARCHIVA
--      (user_funds.archived = true), conservando NAVs y movimientos.
--  (2) Aislamiento estricto: la relación transacción<->fondo y NAV<->fondo usa FK COMPUESTA
--      (user_id, fund_id) -> user_funds(user_id, id), que IMPIDE a nivel de BD referenciar
--      el fondo de otro usuario (no basta con RLS, que no cubre integridad referencial).
--  (3) Identidad estable = user_funds.id (uuid). El símbolo es mutable; external_id del
--      proveedor evita duplicar el mismo fondo.

-- 1) Catálogo de fondos por usuario.
create table if not exists public.user_funds (
  id           uuid not null default gen_random_uuid(),
  user_id      uuid not null default auth.uid() references auth.users(id) on delete cascade,
  symbol       text not null,
  external_id  text,
  name         text,
  provider     text not null default 'fintual',
  currency     text not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  archived     boolean not null default false,       -- archivar en vez de borrar (precaución 1)
  created_at   timestamptz not null default now(),
  primary key (id),
  unique (user_id, id),                              -- objetivo de la FK compuesta (precaución 2)
  unique (user_id, symbol),
  unique (user_id, provider, external_id)
);

-- 2) NAV (valor cuota) manual y fechado. FK compuesta por usuario + RESTRICT.
create table if not exists public.fund_navs (
  id        uuid primary key default gen_random_uuid(),
  user_id   uuid not null default auth.uid() references auth.users(id) on delete cascade,
  fund_id   uuid not null,
  as_of     date not null,
  nav       numeric not null check (nav > 0),
  currency  text not null default 'MXN' check (currency ~ '^[A-Z]{3}$'),
  source    text not null default 'manual',
  created_at timestamptz not null default now(),
  unique (fund_id, as_of),                           -- un NAV por fondo y fecha (idempotente)
  constraint fund_navs_fund_fk foreign key (user_id, fund_id)
    references public.user_funds(user_id, id) on delete restrict
);

-- 3) Enlace con transacciones existentes: columna fund_id NULLABLE + FK compuesta RESTRICT.
--    fund_id NULL => acción/ETF (como hasta hoy); NOT NULL => fondo. Nunca SET NULL (precaución 1):
--    borrar un fondo con movimientos queda BLOQUEADO; se archiva el fondo en su lugar.
alter table public.transactions
  add column if not exists fund_id uuid;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'transactions_fund_fk') then
    alter table public.transactions
      add constraint transactions_fund_fk foreign key (user_id, fund_id)
      references public.user_funds(user_id, id) on delete restrict;
  end if;
end $$;

-- RLS: aislamiento por usuario.
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

-- Convención de aplicación (sin doble conteo):
--   aportación -> 1 fila transactions side='buy'  (fund_id, quantity=participaciones, price=NAV)
--   retiro     -> 1 fila transactions side='sell' (fund_id, quantity=participaciones)
--   efectivo no invertido -> 'deposit'/'withdrawal' (fund_id NULL): NO es movimiento del fondo
--   valorización fondo = Σ(participaciones) × NAV más reciente(<=fecha) × FX(moneda->base)
