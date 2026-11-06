-- 0010_etf_holdings_xray.sql — Portfolio X-Ray. ADITIVA. PENDIENTE DE APROBACIÓN.
-- Correcciones finales: (1) elimina la unicidad antigua (etf,ticker) ya sea CONSTRAINT o
-- ÍNDICE único independiente, y SOLO esa; (2) cada línea referencia su snapshot con FK íntegra;
-- (3) credenciales: escritura solo service role, lectura autenticada.

-- (1) Eliminar la clave antigua (etf,ticker) — sea PRIMARY KEY o UNIQUE (constraint o índice),
-- y SOLO esa — antes de poder volver 'ticker' nullable.
do $$
declare r record;
begin
  for r in
    select con.conname from pg_constraint con
    where con.conrelid='public.etf_holdings'::regclass and con.contype in ('p','u')
      and (select array_agg(a.attname::text order by a.attname::text) from unnest(con.conkey) k
           join pg_attribute a on a.attrelid=con.conrelid and a.attnum=k) = array['etf','ticker']
  loop execute format('alter table public.etf_holdings drop constraint %I', r.conname); end loop;

  for r in
    select i.indexrelid::regclass::text as idx from pg_index i
    where i.indrelid='public.etf_holdings'::regclass and i.indisunique
      and not exists (select 1 from pg_constraint c where c.conindid=i.indexrelid)
      and (select array_agg(a.attname::text order by a.attname::text) from unnest(i.indkey) k
           join pg_attribute a on a.attrelid=i.indrelid and a.attnum=k) = array['etf','ticker']
  loop execute format('drop index if exists %s', r.idx); end loop;
end $$;

alter table public.etf_holdings alter column ticker drop not null;

alter table public.etf_holdings
  add column if not exists provider     text,
  add column if not exists as_of        date,
  add column if not exists captured_at  timestamptz not null default now(),
  add column if not exists name         text,
  add column if not exists cusip        text,
  add column if not exists isin         text,
  add column if not exists figi         text,
  add column if not exists share_class  text,
  add column if not exists company_key  text,
  add column if not exists sector       text,
  add column if not exists asset_class  text not null default 'equity',
  add column if not exists market_value numeric,
  add column if not exists notional     numeric,
  add column if not exists line_key     text;

-- Identificadores de snapshot OBLIGATORIOS (tabla vacía: seguro).
alter table public.etf_holdings alter column etf      set not null;
alter table public.etf_holdings alter column provider set not null;
alter table public.etf_holdings alter column as_of    set not null;
alter table public.etf_holdings alter column line_key set not null;

alter table public.etf_holdings
  add constraint etf_holdings_weight_finite
    check (weight is null or weight::text not in ('NaN','Infinity','-Infinity')),
  add constraint etf_holdings_asof_valid   check (as_of >= date '1990-01-01'),
  add constraint etf_holdings_line_key_ne  check (length(line_key) > 0),
  add constraint etf_holdings_provider_ne  check (length(provider) > 0),
  add constraint etf_holdings_class_valid
    check (asset_class in ('equity','cash','derivative','bond','fx','other','unidentified'));

-- (3) Calidad de snapshot (se crea ANTES de la FK para poder referenciarla).
create table if not exists public.etf_snapshots (
  etf         text not null,
  provider    text not null,
  as_of       date not null,
  status      text not null check (status in ('complete','partial','failed','stale')),
  n_lines     integer,
  weight_sum  numeric,
  equity_pct  numeric,
  captured_at timestamptz not null default now(),
  note        text,
  primary key (etf, provider, as_of)
);

-- (2) Relación íntegra: cada línea pertenece a un snapshot existente.
do $$
begin
  if not exists (select 1 from pg_constraint where conname='etf_holdings_snapshot_fk') then
    alter table public.etf_holdings
      add constraint etf_holdings_snapshot_fk foreign key (etf, provider, as_of)
      references public.etf_snapshots(etf, provider, as_of) on delete restrict;
  end if;
end $$;

create unique index if not exists etf_holdings_snapshot
  on public.etf_holdings (etf, provider, as_of, line_key);
create index if not exists etf_holdings_company on public.etf_holdings (company_key);
create index if not exists etf_holdings_latest  on public.etf_holdings (etf, as_of desc);

-- (3) RLS: lectura autenticada, escritura solo service role (job de ingesta).
alter table public.etf_holdings  enable row level security;
alter table public.etf_snapshots enable row level security;
drop policy if exists etf_holdings_read on public.etf_holdings;
create policy etf_holdings_read on public.etf_holdings for select to authenticated using (true);
drop policy if exists etf_snapshots_read on public.etf_snapshots;
create policy etf_snapshots_read on public.etf_snapshots for select to authenticated using (true);
revoke insert, update, delete on public.etf_holdings  from anon, authenticated;
revoke insert, update, delete on public.etf_snapshots from anon, authenticated;
