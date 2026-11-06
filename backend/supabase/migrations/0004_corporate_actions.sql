-- 0004_corporate_actions.sql — Eventos corporativos (splits / reverse splits).
-- ADITIVA y reversible. NO altera `transactions` ni ninguna tabla existente: las
-- operaciones del usuario quedan intactas. Esta tabla es un REGISTRO HISTÓRICO
-- independiente; el ajuste por split se calcula al derivar posiciones (no se reescribe
-- ninguna transacción), por lo que es idempotente y nunca se aplica dos veces.
--
-- ratio = multiplicador de ACCIONES (forward 10-for-1 => 10; reverse 1-for-10 => 0.1).
-- ex_date = primer día de negociación en base AJUSTADA (para NFLX: 2025-11-17).
-- Clave única (ticker, ex_date): evita duplicar el mismo evento.
--
-- Escritura: solo el job (service role). Lectura: usuarios autenticados.

create table if not exists public.corporate_actions (
  id          bigint generated always as identity primary key,
  ticker      text not null,
  action_type text not null default 'split',   -- 'split' | 'reverse_split'
  ratio       numeric not null,                -- multiplicador de acciones (>0)
  ex_date     date not null,                   -- primer día en base ajustada
  numerator   integer,                         -- p.ej. 10 (de "10:1")
  denominator integer,                         -- p.ej. 1
  source      text not null default 'yahoo',
  note        text,
  created_at  timestamptz not null default now(),
  unique (ticker, ex_date)
);

comment on table public.corporate_actions is
  'Splits/reverse splits por instrumento. ratio = multiplicador de acciones; ex_date = primer día ajustado. Registro independiente; las transacciones no se modifican.';

create index if not exists corporate_actions_ticker_idx on public.corporate_actions (ticker);

alter table public.corporate_actions enable row level security;

drop policy if exists corporate_actions_read on public.corporate_actions;
create policy corporate_actions_read on public.corporate_actions
  for select to authenticated using (true);
-- Sin policy de escritura: solo el service role (job) escribe.
