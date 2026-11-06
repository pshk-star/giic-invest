-- 0007_pit_hardening.sql — Endurecimiento del registro point-in-time. ADITIVA e IDEMPOTENTE.
-- Requiere 0006. NO borra ni modifica predicciones existentes.
--
-- Correcciones de esta versión final:
--  (1) horizon_sessions: CHECK NOT VALID (horizon_sessions IS NOT NULL AND > 0) => toda fila
--      NUEVA debe tener horizonte positivo; las heredadas (si existieran) NO se tocan ni se
--      convierten (no se inventan días->sesiones). Para heredadas se incluye, comentada, una
--      estrategia manual explícita.
--  (2) UNIQUE de 0006: se elimina SOLO la restricción cuya definición es EXACTAMENTE
--      UNIQUE (model_name, model_version, ticker, as_of, horizon_days) — no cualquiera que
--      contenga horizon_days.
--  (3) Integridad: CHECK (evaluate_on > as_of). La correspondencia exacta de evaluate_on con
--      el calendario bursátil se garantiza en la APLICACIÓN (se calcula avanzando sobre las
--      SESIONES reales de price_history, que ya excluyen fines de semana y feriados); la BD
--      garantiza la monotonicidad. Prueba automática app-side (test_calendar.py).
--  (4) Experimentos: se añade run_id; el UNIQUE incluye origin+run_id, de modo que distintas
--      corridas legítimas de backtest coexisten sin sobrescribir, y re-ejecutar la MISMA
--      corrida es idempotente (ON CONFLICT DO NOTHING). Producción se identifica con
--      origin='production'.
--  (5)(6) Inmutabilidad (triggers), permisos (REVOKE), e idempotencia; verificado contra el
--      esquema real de 0006 y con un cluster Postgres local (ver 0007_selftest.sql).

alter table public.predictions
  add column if not exists origin           text not null default 'backtest',
  add column if not exists emitted_at        timestamptz,
  add column if not exists data_ref          jsonb,
  add column if not exists horizon_sessions  integer,
  add column if not exists calendar          text not null default 'XNYS',
  add column if not exists run_id            text;

-- (1) horizon_days deja de ser obligatorio (producción usa horizon_sessions).
alter table public.predictions alter column horizon_days drop not null;

-- (2) Eliminar SOLO el UNIQUE original exacto de 0006.
do $$
declare c text;
begin
  select conname into c
    from pg_constraint
   where conrelid = 'public.predictions'::regclass and contype = 'u'
     and pg_get_constraintdef(oid) = 'UNIQUE (model_name, model_version, ticker, as_of, horizon_days)';
  if c is not null then
    execute format('alter table public.predictions drop constraint %I', c);
  end if;
end $$;

-- CHECKs NOT VALID: se aplican a filas NUEVAS; no validan ni modifican heredadas.
do $$
begin
  if not exists (select 1 from pg_constraint where conname='predictions_horizon_pos_chk') then
    alter table public.predictions add constraint predictions_horizon_pos_chk
      check (horizon_sessions is not null and horizon_sessions > 0) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname='predictions_eval_after_asof_chk') then
    alter table public.predictions add constraint predictions_eval_after_asof_chk
      check (evaluate_on > as_of) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname='predictions_origin_chk') then
    alter table public.predictions add constraint predictions_origin_chk
      check (origin in ('backtest','production')) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname='predictions_production_fields_chk') then
    alter table public.predictions add constraint predictions_production_fields_chk
      check (origin <> 'production' or (emitted_at is not null and data_ref is not null)) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname='predictions_run_id_chk') then
    alter table public.predictions add constraint predictions_run_id_chk
      check (run_id is not null) not valid;
  end if;
  if not exists (select 1 from pg_constraint where conname='predictions_calendar_chk') then
    alter table public.predictions add constraint predictions_calendar_chk
      check (char_length(calendar) between 2 and 16) not valid;
  end if;
end $$;

-- Estrategia para registros heredados (si existieran), explícita y manual — NO automática:
--   1) Revisar: select id, horizon_days, horizon_sessions from public.predictions where horizon_sessions is null;
--   2) Asignar horizon_sessions con el horizonte real de cada modelo (sin conversión ciega de días).
--   3) Luego: alter table public.predictions validate constraint predictions_horizon_pos_chk;

-- (4) Unicidad: separa origin y corridas (run_id); en sesiones.
create unique index if not exists predictions_uniq_origin_run
  on public.predictions (origin, model_name, model_version, run_id, ticker, as_of, horizon_sessions);

-- (5) Inmutabilidad real.
create or replace function public.prevent_mutation()
returns trigger language plpgsql as $$
begin
  raise exception 'Tabla append-only: % no permitido en %', TG_OP, TG_TABLE_NAME
    using errcode = 'check_violation';
end;
$$;

drop trigger if exists predictions_append_only on public.predictions;
create trigger predictions_append_only before update or delete on public.predictions
  for each row execute function public.prevent_mutation();
drop trigger if exists pit_snapshots_append_only on public.pit_snapshots;
create trigger pit_snapshots_append_only before update or delete on public.pit_snapshots
  for each row execute function public.prevent_mutation();
drop trigger if exists prediction_outcomes_append_only on public.prediction_outcomes;
create trigger prediction_outcomes_append_only before update or delete on public.prediction_outcomes
  for each row execute function public.prevent_mutation();

-- Permisos (defensa en profundidad; RLS ya bloquea escritura de anon/authenticated).
revoke update, delete on public.predictions        from anon, authenticated;
revoke update, delete on public.pit_snapshots       from anon, authenticated;
revoke update, delete on public.prediction_outcomes from anon, authenticated;
