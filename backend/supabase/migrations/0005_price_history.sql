-- 0005_price_history.sql — Histórico diario de precios (base para Research y forecasting).
-- ADITIVA y reversible. NO altera tablas existentes. Independiente de `prices` (último
-- cierre) y de `quotes` (cotización reciente): aquí vive la SERIE diaria.
--
-- `close`     : cierre AJUSTADO por splits y distribuciones (adjclose de la fuente).
-- `adjusted`  : true => la serie está ajustada (para gráficos y retornos comparables).
-- `reconstructed`: true  => backfill histórico traído hoy desde la fuente (NO es un
--                            snapshot capturado en su día);
--                 false => cierre EOD capturado realmente ese día por el job.
--   (Separa históricos reconstruidos de capturas reales — requisito point-in-time.)
-- Clave (ticker, as_of): evita duplicados; el backfill es idempotente.
--
-- Escritura: solo el job (service role). Lectura: usuarios autenticados.

create table if not exists public.price_history (
  ticker        text not null,
  as_of         date not null,
  close         numeric not null,
  volume        numeric,
  adjusted      boolean not null default true,
  reconstructed boolean not null default true,
  source        text not null default 'yahoo',
  updated_at    timestamptz not null default now(),
  primary key (ticker, as_of)
);

comment on table public.price_history is
  'Serie diaria de cierres ajustados por ticker. reconstructed=true: backfill histórico; false: captura EOD real del día.';

create index if not exists price_history_ticker_idx on public.price_history (ticker, as_of);

alter table public.price_history enable row level security;

drop policy if exists price_history_read on public.price_history;
create policy price_history_read on public.price_history
  for select to authenticated using (true);
-- Sin policy de escritura: solo el service role (job) escribe.
