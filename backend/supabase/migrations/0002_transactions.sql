-- GIIC v0.4 — Fase A: registro de operaciones e instrumentos de referencia.
-- Migración ADITIVA, segura y reversible: NO altera ni borra tablas existentes.
-- Ejecutar en Supabase → SQL Editor → Run. Idempotente (IF NOT EXISTS).

-- ----------------------------------------------------------------------------
-- TRANSACCIONES: fuente de verdad de la cartera (privada por usuario).
-- Las posiciones se DERIVAN de aquí; no se edita una tabla de posiciones.
-- ----------------------------------------------------------------------------
create table if not exists public.transactions (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  ticker      text not null,
  side        text not null check (side in
                ('buy','sell','dividend','deposit','withdrawal','split')),
  quantity    numeric,          -- acciones (buy/sell), o ratio (split). Permite fracciones.
  price       numeric,          -- precio por acción (buy/sell)
  fees        numeric not null default 0,
  amount      numeric,          -- efectivo (dividend/deposit/withdrawal)
  currency    text not null default 'USD',
  executed_at date not null,
  notes       text,
  created_at  timestamptz not null default now()
);
create index if not exists idx_tx_user on public.transactions (user_id, ticker, executed_at);

alter table public.transactions enable row level security;
drop policy if exists transactions_owner on public.transactions;
create policy transactions_owner on public.transactions
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- ----------------------------------------------------------------------------
-- INSTRUMENTOS DE REFERENCIA: identificación verificable (nombre, tipo, bolsa,
-- moneda). Compartida (solo lectura para autenticados); la escribe el job.
-- status: 'resolved' (identificado) | 'pending' (aún sin verificar).
-- ----------------------------------------------------------------------------
create table if not exists public.instruments (
  ticker      text primary key,
  name        text,
  asset_class text,              -- equity | etf | unknown
  exchange    text,
  currency    text default 'USD',
  sector      text,
  status      text not null default 'pending',
  source      text,              -- de dónde se identificó (yahoo/edgar/universe)
  updated_at  timestamptz not null default now()
);

alter table public.instruments enable row level security;
drop policy if exists instruments_read on public.instruments;
create policy instruments_read on public.instruments
  for select to authenticated using (true);

-- ----------------------------------------------------------------------------
-- REVERSIÓN (si alguna vez hiciera falta deshacer esta migración):
--   drop table if exists public.transactions;
--   drop table if exists public.instruments;
-- (No se ejecuta aquí; queda documentado.)
-- ----------------------------------------------------------------------------
