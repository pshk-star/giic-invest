-- 0010_etf_holdings_xray.sql — Enriquecer etf_holdings para Portfolio X-Ray.
-- ADITIVA. etf_holdings ya existe (etf, ticker, weight). PENDIENTE DE APROBACIÓN: no ejecutar.
-- Añade procedencia, fechas, identificador estable y clase de activo para calcular la
-- exposición efectiva real sin inventar y sin atribuir el 100% a acciones.

alter table public.etf_holdings
  add column if not exists provider    text,                 -- 'ishares'|'vanguard'|'invesco'|'vaneck'|'ssga'
  add column if not exists as_of       date,                 -- fecha de vigencia del holding (del emisor)
  add column if not exists captured_at timestamptz default now(),  -- cuándo lo capturamos
  add column if not exists name        text,                 -- nombre del subyacente
  add column if not exists cusip       text,                 -- identificador estable (si el emisor lo publica)
  add column if not exists asset_class text default 'equity';-- equity|cash|derivative|bond|other

-- Un snapshot por (etf, proveedor, fecha, ticker): conserva historia, no sobrescribe.
create unique index if not exists etf_holdings_snapshot
  on public.etf_holdings (etf, provider, as_of, ticker);

-- RLS: lectura para autenticados (dato de mercado); escritura solo service role (jobs).
alter table public.etf_holdings enable row level security;
drop policy if exists etf_holdings_read on public.etf_holdings;
create policy etf_holdings_read on public.etf_holdings for select to authenticated using (true);
revoke insert, update, delete on public.etf_holdings from anon, authenticated;
