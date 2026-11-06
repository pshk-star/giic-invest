-- 0007_selftest.sql — Pruebas de 0007. Ejecutar DESPUÉS de 0006+0007.
-- Es transaccional y termina con ROLLBACK: no deja datos. Imprime PASS/FAIL por caso.
-- (En Supabase: pégalo en el SQL editor; corre dentro de una transacción y revierte.)
begin;

-- 1) backtest válido -> OK
insert into public.predictions
  (model_name, model_version, run_id, origin, ticker, as_of, horizon_sessions, evaluate_on, prediction, calendar)
values ('mf','v1','bt-2026-11-05','backtest','MU','2026-01-05',20,'2026-02-03','{"rel_return":0.01}','XNYS');
do $$ begin raise notice 'CASO 1 backtest válido: PASS'; end $$;

-- 2) producción válida (emitted_at + data_ref) -> OK
insert into public.predictions
  (model_name, model_version, run_id, origin, ticker, as_of, horizon_sessions, evaluate_on, prediction,
   emitted_at, data_ref, calendar)
values ('mf','v1','prod-2026-11-05','production','MU','2026-11-05',20,'2026-12-03','{"rel_return":0.02}',
        now(), '{"price_asof":"2026-11-05","data_version":"ph-1"}','XNYS');
do $$ begin raise notice 'CASO 2 producción válida: PASS'; end $$;

-- 3) producción sin emitted_at/data_ref -> DEBE fallar
do $$ begin
  insert into public.predictions (model_name,model_version,run_id,origin,ticker,as_of,horizon_sessions,evaluate_on,prediction,calendar)
  values ('mf','v1','prod-x','production','MU','2026-11-05',20,'2026-12-03','{}','XNYS');
  raise exception 'CASO 3: FAIL (se permitió producción sin emitted_at/data_ref)';
exception when check_violation then raise notice 'CASO 3 rechazo producción incompleta: PASS'; end $$;

-- 4) horizon_sessions = 0 y NULL -> DEBEN fallar
do $$ begin
  insert into public.predictions (model_name,model_version,run_id,origin,ticker,as_of,horizon_sessions,evaluate_on,prediction,calendar)
  values ('mf','v1','bt-h0','backtest','MU','2026-01-05',0,'2026-02-03','{}','XNYS');
  raise exception 'CASO 4a: FAIL (se permitió horizon_sessions=0)';
exception when check_violation then raise notice 'CASO 4a horizonte 0: PASS'; end $$;
do $$ begin
  insert into public.predictions (model_name,model_version,run_id,origin,ticker,as_of,horizon_sessions,evaluate_on,prediction,calendar)
  values ('mf','v1','bt-hnull','backtest','MU','2026-01-05',null,'2026-02-03','{}','XNYS');
  raise exception 'CASO 4b: FAIL (se permitió horizon_sessions NULL)';
exception when check_violation then raise notice 'CASO 4b horizonte NULL: PASS'; end $$;

-- 5) evaluate_on <= as_of -> DEBE fallar
do $$ begin
  insert into public.predictions (model_name,model_version,run_id,origin,ticker,as_of,horizon_sessions,evaluate_on,prediction,calendar)
  values ('mf','v1','bt-eval','backtest','MU','2026-02-03',20,'2026-01-05','{}','XNYS');
  raise exception 'CASO 5: FAIL (evaluate_on <= as_of permitido)';
exception when check_violation then raise notice 'CASO 5 evaluate_on<=as_of: PASS'; end $$;

-- 6) UPDATE y DELETE -> DEBEN fallar (append-only)
do $$ begin
  update public.predictions set prediction='{"x":1}' where run_id='bt-2026-11-05';
  raise exception 'CASO 6a: FAIL (UPDATE permitido)';
exception when check_violation then raise notice 'CASO 6a rechazo UPDATE: PASS'; end $$;
do $$ begin
  delete from public.predictions where run_id='bt-2026-11-05';
  raise exception 'CASO 6b: FAIL (DELETE permitido)';
exception when check_violation then raise notice 'CASO 6b rechazo DELETE: PASS'; end $$;

-- 7) re-insertar la MISMA corrida con ON CONFLICT DO NOTHING -> no duplica
insert into public.predictions
  (model_name,model_version,run_id,origin,ticker,as_of,horizon_sessions,evaluate_on,prediction,calendar)
values ('mf','v1','bt-2026-11-05','backtest','MU','2026-01-05',20,'2026-02-03','{"rel_return":0.01}','XNYS')
on conflict do nothing;
do $$ declare n int; begin
  select count(*) into n from public.predictions where origin='backtest' and run_id='bt-2026-11-05' and ticker='MU' and horizon_sessions=20;
  if n=1 then raise notice 'CASO 7 idempotencia (sin duplicado): PASS'; else raise exception 'CASO 7: FAIL (n=%)', n; end if;
end $$;

-- 8) segunda corrida legítima de backtest (otro run_id) -> coexiste
insert into public.predictions
  (model_name,model_version,run_id,origin,ticker,as_of,horizon_sessions,evaluate_on,prediction,calendar)
values ('mf','v1','bt-2026-11-06','backtest','MU','2026-01-05',20,'2026-02-03','{"rel_return":0.03}','XNYS');
do $$ declare n int; begin
  select count(*) into n from public.predictions where origin='backtest' and ticker='MU' and horizon_sessions=20;
  if n=2 then raise notice 'CASO 8 múltiples corridas coexisten: PASS'; else raise exception 'CASO 8: FAIL (n=%)', n; end if;
end $$;

-- 9) segunda predicción de PRODUCCIÓN con misma clave y distinto run_id -> DEBE fallar
do $$ begin
  insert into public.predictions
    (model_name,model_version,run_id,origin,ticker,as_of,horizon_sessions,evaluate_on,prediction,emitted_at,data_ref,calendar)
  values ('mf','v1','prod-OTRO','production','MU','2026-11-05',20,'2026-12-03','{"rel_return":0.02}',
          now(),'{"price_asof":"2026-11-05"}','XNYS');
  raise exception 'CASO 9: FAIL (se permitió una segunda producción oficial con otro run_id)';
exception when unique_violation then raise notice 'CASO 9 producción oficial única: PASS'; end $$;

rollback;
