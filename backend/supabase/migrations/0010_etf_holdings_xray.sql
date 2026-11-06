-- 0010_etf_holdings_xray.sql — Portfolio X-Ray: holdings de ETFs con procedencia, fechas,
-- identificadores estables y clase de activo. ADITIVA. PENDIENTE DE APROBACIÓN: no ejecutar.
--
-- Modelo corregido:
--  * NO depende solo del ticker: ticker pasa a NULLABLE (efectivo/derivados/sin ticker).
--  * Identificador de INSTRUMENTO (ticker, cusip, isin, figi, share_class) distinto del
--    identificador de EMPRESA (company_key) para consolidar exposición entre clases de acción
--    y múltiples instrumentos del mismo emisor.
--  * line_key = clave estable de la LÍNEA del holding (para idempotencia del upsert).
--  * asset_class distingue equity|cash|derivative|bond|fx|other|unidentified -> lo no
--    identificado se registra como tal, nunca se atribuye a acciones.
--  * Snapshots históricos: unicidad por (etf, provider, as_of, line_key); no se sobrescribe.

-- ticker deja de ser obligatorio (puede no existir para efectivo/derivados).
alter table public.etf_holdings alter column ticker drop not null;

alter table public.etf_holdings
  add column if not exists provider     text,
  add column if not exists as_of        date,                      -- fecha efectiva (del emisor)
  add column if not exists captured_at  timestamptz not null default now(),
  add column if not exists name         text,
  add column if not exists cusip        text,
  add column if not exists isin         text,
  add column if not exists figi         text,
  add column if not exists share_class  text,                      -- p.ej. GOOGL vs GOOG
  add column if not exists company_key  text,                      -- id de EMPRESA (emisor) para consolidar
  add column if not exists asset_class  text not null default 'equity',
  add column if not exists market_value numeric,
  add column if not exists shares       numeric,
  add column if not exists line_key     text;                      -- clave estable de la línea

-- Quitar cualquier restricción UNIQUE previa (p.ej. sobre (etf,ticker)) que impida snapshots
-- por fecha. La tabla está vacía; es seguro. Redefinimos la unicidad abajo.
do $$
declare r record;
begin
  for r in select conname from pg_constraint
           where conrelid = 'public.etf_holdings'::regclass and contype = 'u'
  loop
    execute format('alter table public.etf_holdings drop constraint %I', r.conname);
  end loop;
end $$;

-- Un snapshot por (etf, proveedor, fecha, línea). Conserva historia (no sobrescribe fechas previas).
create unique index if not exists etf_holdings_snapshot
  on public.etf_holdings (etf, provider, as_of, line_key);

create index if not exists etf_holdings_company on public.etf_holdings (company_key);
create index if not exists etf_holdings_latest  on public.etf_holdings (etf, as_of desc);

-- RLS: lectura para autenticados (dato de mercado); escritura solo service role (jobs).
alter table public.etf_holdings enable row level security;
drop policy if exists etf_holdings_read on public.etf_holdings;
create policy etf_holdings_read on public.etf_holdings for select to authenticated using (true);
revoke insert, update, delete on public.etf_holdings from anon, authenticated;
