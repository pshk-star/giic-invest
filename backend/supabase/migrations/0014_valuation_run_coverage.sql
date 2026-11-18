-- Additive: preserves all 0013 history, including pre-manifest publications.
-- Only manifest-backed, complete runs may govern. Partial runs are diagnostics.
begin;
create table public.valuation_runs (
  id bigint generated always as identity primary key,
  run_id uuid not null unique,
  run_kind text not null check (run_kind in ('full','partial')),
  universe_version text not null,
  requested_tickers text[] not null,
  published_at timestamptz not null default clock_timestamp()
);
alter table public.valuation_runs enable row level security;
-- Supabase may auto-grant ALL through default privileges; override those grants explicitly.
revoke all on public.valuation_runs, public.valuation_snapshots from public, anon, authenticated, service_role;
revoke all on sequence public.valuation_runs_id_seq, public.valuation_snapshots_id_seq
  from public, anon, authenticated, service_role;
grant select on public.valuation_runs, public.valuation_snapshots to authenticated, service_role;
create policy valuation_runs_read on public.valuation_runs for select to authenticated using (true);
create trigger valuation_runs_immutable before update or delete on public.valuation_runs
for each row execute function public.valuation_immutable();
-- Prevent the old RPC or direct writer from publishing rows without an admitted manifest.
drop function public.publish_valuations(uuid,jsonb);
-- Direct writes and sequence manipulation remain denied, even to the publisher role.
create function public.publish_valuations(p_run_id uuid, p_rows jsonb, p_manifest jsonb) returns integer
language plpgsql security definer set search_path = pg_catalog, public, pg_temp as $$
declare
  requested text[];
  produced text[];
  kind text := p_manifest->>'run_kind';
  version text := p_manifest->>'universe_version';
  previous public.valuation_runs%rowtype;
  n integer;
begin
  perform pg_advisory_xact_lock(7130013);
  if p_run_id is null or jsonb_typeof(p_manifest) is distinct from 'object'
     or kind is null or kind not in ('full','partial') or version is distinct from 'giic-38-v1'
     or jsonb_typeof(p_manifest->'requested_tickers') is distinct from 'array'
     or jsonb_typeof(p_rows) is distinct from 'array' then
    raise exception 'invalid publication manifest';
  end if;
  select array_agg(t order by t) into requested
    from jsonb_array_elements_text(p_manifest->'requested_tickers') t;
  select array_agg(r->>'ticker' order by r->>'ticker') into produced from jsonb_array_elements(p_rows) r;
  if requested is null or requested is distinct from produced
     or cardinality(requested) <> (select count(distinct t) from unnest(requested) t)
     or exists(select 1 from unnest(requested) t where t is null or t !~ '^[A-Z0-9][A-Z0-9.-]*$') then
    raise exception 'requested/produced coverage mismatch or duplicate ticker';
  end if;
  if kind='full' and requested is distinct from array['AAPL','ABBV','ADBE','AMGN','AMT','AMZN','ASML','CAT','CL','COP','CVX','DUK','EOG','FCX','GE','GOOGL','HD','JNJ','KO','LLY','LMT','LOW','MCD','META','MRK','MSFT','NEE','NFLX','NVDA','PEP','PFE','PG','PLD','RTX','SHW','TSM','UPS','XOM']::text[] then
    raise exception 'full run must cover the exact giic-38-v1 universe';
  end if;
  if exists(select 1 from jsonb_array_elements(p_rows) r
    where jsonb_typeof(r->'payload') is distinct from 'object'
      or r->'payload'->>'ticker' is distinct from r->>'ticker'
      or coalesce(r->'payload'->>'status','') not in ('consistente','en_revision','no_valorable')
      or r->'payload'->>'run_id' is distinct from p_run_id::text
      or r->'payload'->>'run_kind' is distinct from kind) then
    raise exception 'invalid valuation payload';
  end if;
  select * into previous from public.valuation_runs where run_id=p_run_id;
  if found then
    if previous.run_kind is distinct from kind or previous.universe_version is distinct from version
       or previous.requested_tickers is distinct from requested
       or (select jsonb_agg(jsonb_build_object('ticker',ticker,'payload',payload) order by ticker)
           from public.valuation_snapshots where run_id=p_run_id)
          is distinct from (select jsonb_agg(r order by r->>'ticker') from jsonb_array_elements(p_rows) r) then
      raise exception 'run_id reused with different manifest or payload';
    end if;
    return 0;
  end if;
  if exists(select 1 from public.valuation_snapshots where run_id=p_run_id) then
    raise exception 'cannot adopt a legacy publication';
  end if;
  insert into public.valuation_runs(run_id,run_kind,universe_version,requested_tickers)
    values(p_run_id,kind,version,requested);
  insert into public.valuation_snapshots(run_id,ticker,payload)
    select p_run_id,r->>'ticker',r->'payload' from jsonb_array_elements(p_rows) r;
  get diagnostics n = row_count;
  return n;
end;
$$;
revoke all on function public.publish_valuations(uuid,jsonb,jsonb) from public, anon, authenticated, service_role;
grant execute on function public.publish_valuations(uuid,jsonb,jsonb) to service_role;
commit;
