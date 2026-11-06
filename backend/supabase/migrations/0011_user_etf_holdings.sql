-- 0011_user_etf_holdings.sql — Importación MANUAL de holdings oficiales por usuario (CSV/XLSX).
-- ADITIVA. RLS por usuario. PENDIENTE DE APROBACIÓN: no ejecutar.
-- Para ETFs sin descarga automática (p.ej. VOO/QQQ/SCHD, cuyos emisores bloquean servidores),
-- el usuario sube el archivo OFICIAL del emisor desde su navegador. Se conserva la procedencia
-- (source_file, provider, as_of). No sustituye a los snapshots automáticos; el X-Ray usa, por ETF,
-- la composición manual más reciente o la automática 'complete', la que exista/sea más nueva.

create table if not exists public.user_etf_holdings (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users(id) on delete cascade,
  etf         text not null,
  as_of       date not null check (as_of >= date '1990-01-01'),
  provider    text not null default 'manual',
  source_file text,
  ticker      text,
  name        text,
  cusip       text,
  company_key text,
  sector      text,
  asset_class text not null default 'equity'
    check (asset_class in ('equity','cash','derivative','bond','fx','commodity','other','unidentified')),
  weight      numeric check (weight is null or weight::text not in ('NaN','Infinity','-Infinity')),
  line_key    text not null check (length(line_key) > 0),
  captured_at timestamptz not null default now(),
  unique (user_id, etf, as_of, line_key)
);

alter table public.user_etf_holdings enable row level security;
drop policy if exists user_etf_holdings_owner on public.user_etf_holdings;
create policy user_etf_holdings_owner on public.user_etf_holdings
  for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create index if not exists user_etf_holdings_lookup on public.user_etf_holdings (user_id, etf, as_of desc);
