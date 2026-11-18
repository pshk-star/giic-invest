-- P0: dedicated immutable publication feed. Does not rewrite PIT research history.
-- Apply before the new writer/frontend. No automatic production migration.
begin;
create table public.valuation_snapshots (
  id bigint generated always as identity primary key,
  run_id uuid not null,
  ticker text not null,
  captured_at timestamptz not null default clock_timestamp(),
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  unique (run_id, ticker)
);
create index on public.valuation_snapshots(ticker, id desc);
alter table public.valuation_snapshots enable row level security;
grant select on public.valuation_snapshots to authenticated;
grant select, insert on public.valuation_snapshots to service_role;
grant usage, select on sequence public.valuation_snapshots_id_seq to service_role;
create policy valuation_read on public.valuation_snapshots for select to authenticated using (true);

create function public.valuation_immutable() returns trigger language plpgsql as $$
begin raise exception 'valuation publication is immutable'; end;
$$;
create trigger valuation_immutable before update or delete on public.valuation_snapshots
for each row execute function public.valuation_immutable();

create function public.publish_valuations(p_run_id uuid, p_rows jsonb) returns integer
language plpgsql security invoker set search_path = public, pg_temp as $$
declare n integer;
begin
  -- Serialize publication transactions; identity order is therefore publication order.
  perform pg_advisory_xact_lock(7130013);
  if jsonb_typeof(p_rows) is distinct from 'array' or jsonb_array_length(p_rows) = 0 then
    raise exception 'nonempty valuation batch required';
  end if;
  if exists (select 1 from jsonb_array_elements(p_rows) r
    where coalesce(r->>'ticker','') = '' or jsonb_typeof(r->'payload') is distinct from 'object'
       or (r->'payload'->>'ticker') is distinct from (r->>'ticker')
       or coalesce(r->'payload'->>'status','') not in ('consistente','en_revision','no_valorable')) then
    raise exception 'invalid valuation payload';
  end if;
  -- Same request ID may be retried only with exactly the same batch.
  if exists (select 1 from valuation_snapshots where run_id = p_run_id) then
    if (select jsonb_agg(jsonb_build_object('ticker',ticker,'payload',payload) order by ticker)
        from valuation_snapshots where run_id=p_run_id)
       is distinct from
       (select jsonb_agg(r order by r->>'ticker') from jsonb_array_elements(p_rows) r) then
      raise exception 'run_id reused with different valuation payload';
    end if;
    return 0;
  end if;
  insert into valuation_snapshots(run_id,ticker,payload)
    select p_run_id,r->>'ticker',r->'payload' from jsonb_array_elements(p_rows) r;
  get diagnostics n = row_count;
  return n;
end;
$$;
revoke all on function public.publish_valuations(uuid,jsonb) from public;
grant execute on function public.publish_valuations(uuid,jsonb) to service_role;
commit;
