-- 0003_quotes.sql — Cotizaciones recientes (snapshot intradía/último disponible).
-- ADITIVA y reversible. No altera tablas existentes. No cambia precios EOD (`prices`),
-- que siguen siendo el cierre para P&L histórico; `quotes` guarda la ÚLTIMA cotización
-- observada con su hora real, cambio del día, rango de sesión, volumen y estado de mercado.
--
-- Escritura: solo el job (service role, omite RLS). Lectura: usuarios autenticados.
-- Nunca se guarda un precio inventado; si una cotización falla, el job NO toca la fila
-- previa (se conserva el último valor válido con su hora).

create table if not exists public.quotes (
  ticker         text primary key,
  price          numeric not null,          -- último precio disponible
  previous_close numeric,                   -- cierre previo (para cambio del día)
  change         numeric,                   -- price - previous_close (USD)
  change_pct     numeric,                   -- cambio del día en fracción (0.012 = 1.2%)
  day_high       numeric,
  day_low        numeric,
  volume         numeric,
  currency       text not null default 'USD',
  exchange       text,
  market_state   text,                      -- 'REGULAR' | 'PRE' | 'POST' | 'CLOSED' | null
  quote_time     timestamptz not null,      -- HORA REAL de la cotización (de la fuente)
  source         text not null default 'yahoo',
  delayed        boolean not null default true,   -- gratis => asumir retrasado, nunca 'tiempo real'
  updated_at     timestamptz not null default now()
);

comment on table public.quotes is
  'Última cotización observada por instrumento (job GitHub Actions). Gratis y retrasada; quote_time es la hora real de la fuente.';

alter table public.quotes enable row level security;

drop policy if exists quotes_read on public.quotes;
create policy quotes_read on public.quotes
  for select to authenticated using (true);
-- Sin policy de escritura: solo el service role (job) escribe.
