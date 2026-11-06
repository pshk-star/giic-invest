-- 0008_selftest.sql — Pruebas de 0008 (tras 0006+0007+0008). Transaccional: ROLLBACK final.
begin;

-- 1) dos filings el MISMO día, distinto accession -> coexisten (sin colisión)
insert into public.fundamentals_pit (provider,ticker,accession,form_type,concept,context_ref,unit,period_end,filing_date,value)
values ('edgar','MU','0001-A','10-Q','Revenues','C1','USD','2026-06-30','2026-08-01',100),
       ('edgar','MU','0002-B','8-K','Revenues','C1','USD','2026-06-30','2026-08-01',101);
do $$ declare n int; begin
  select count(*) into n from public.fundamentals_pit where ticker='MU' and filing_date='2026-08-01';
  if n=2 then raise notice 'CASO 1 dos filings mismo día: PASS'; else raise exception 'CASO 1 FAIL (n=%)',n; end if;
end $$;

-- 2) reexpresión posterior (otro accession) = fila nueva, no sobrescribe
insert into public.fundamentals_pit (provider,ticker,accession,form_type,concept,context_ref,unit,period_end,filing_date,value,amended)
values ('edgar','MU','0003-AMD','10-Q/A','Revenues','C1','USD','2026-06-30','2026-11-01',105,true);
do $$ declare n int; begin
  select count(*) into n from public.fundamentals_pit where ticker='MU' and concept='Revenues' and period_end='2026-06-30';
  if n=3 then raise notice 'CASO 2 reexpresión como fila nueva: PASS'; else raise exception 'CASO 2 FAIL (n=%)',n; end if;
end $$;

-- 3) duplicado exacto (mismo accession+concept+context+unit) idempotente (DO NOTHING)
insert into public.fundamentals_pit (provider,ticker,accession,form_type,concept,context_ref,unit,period_end,filing_date,value)
values ('edgar','MU','0001-A','10-Q','Revenues','C1','USD','2026-06-30','2026-08-01',100)
on conflict do nothing;
do $$ declare n int; begin
  select count(*) into n from public.fundamentals_pit where accession='0001-A' and concept='Revenues' and context_ref='C1' and unit='USD';
  if n=1 then raise notice 'CASO 3 idempotencia por documento estable: PASS'; else raise exception 'CASO 3 FAIL (n=%)',n; end if;
end $$;

-- 4) fundamentals_pit append-only: UPDATE/DELETE rechazados
do $$ begin update public.fundamentals_pit set value=999 where accession='0001-A';
  raise exception 'CASO 4a FAIL (UPDATE permitido)';
exception when check_violation then raise notice 'CASO 4a fundamentals append-only UPDATE: PASS'; end $$;

-- 5) macro_pit: dos vintages del mismo obs_date coexisten (revisión)
insert into public.macro_pit (provider,series_id,obs_date,value,release_date,vintage,revision)
values ('alfred','CPIAUCSL','2026-09-01',311.2,'2026-10-10','2026-10-10',0),
       ('alfred','CPIAUCSL','2026-09-01',311.5,'2026-11-12','2026-11-12',1);
do $$ declare n int; begin
  select count(*) into n from public.macro_pit where series_id='CPIAUCSL' and obs_date='2026-09-01';
  if n=2 then raise notice 'CASO 5 vintages coexisten: PASS'; else raise exception 'CASO 5 FAIL (n=%)',n; end if;
end $$;

-- 6) price_adjustment_lineage append-only + reconstrucción por snapshot_id
insert into public.price_adjustment_lineage (snapshot_id,ticker,adjusted_through,actions_hash,n_actions)
values ('snap-2026-11-05','MU','2026-11-05','abc123',2);
do $$ begin update public.price_adjustment_lineage set n_actions=9 where snapshot_id='snap-2026-11-05';
  raise exception 'CASO 6 FAIL (UPDATE permitido)';
exception when check_violation then raise notice 'CASO 6 lineage append-only: PASS'; end $$;

rollback;
