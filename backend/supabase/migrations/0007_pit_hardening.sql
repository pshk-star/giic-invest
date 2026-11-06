-- 0007_pit_hardening.sql — Endurecimiento del registro point-in-time. ADITIVA.
-- Corrige: (1) inmutabilidad REAL (no solo UNIQUE), (2) diferenciación backtest vs
-- producción con fecha de emisión / versión / referencia de datos, (3) horizontes en
-- SESIONES bursátiles (no días calendario).
--
-- Requiere que 0006 ya exista. Es segura: las tablas están vacías (sin filas que migrar).

-- ------------------------------------------------------------------ (2) y (3)
alter table public.predictions
  add column if not exists origin           text not null default 'backtest',  -- 'backtest'|'production'
  add column if not exists emitted_at        timestamptz,                        -- fecha/hora EFECTIVA de emisión
  add column if not exists data_ref          jsonb,                              -- referencia a los datos usados (p.ej. {price_asof, data_version, snapshot_ids})
  add column if not exists horizon_sessions  integer,                            -- horizonte en SESIONES bursátiles
  add column if not exists calendar          text not null default 'XNYS';       -- calendario bursátil usado

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'predictions_origin_chk') then
    alter table public.predictions add constraint predictions_origin_chk
      check (origin in ('backtest','production'));
  end if;
end $$;

-- Unicidad que SEPARA backtest de producción y usa el horizonte en sesiones:
-- una predicción histórica (backtest) no puede confundirse con una de producción.
create unique index if not exists predictions_uniq_origin
  on public.predictions (origin, model_name, model_version, ticker, as_of, horizon_sessions);

-- ------------------------------------------------------------------ (1) Inmutabilidad real
-- Las restricciones UNIQUE no impiden UPDATE/DELETE. Un trigger que rechaza UPDATE y DELETE
-- hace las tablas APPEND-ONLY para CUALQUIER rol, incluido el service role de los jobs
-- (los triggers se disparan sin importar el rol; RLS no aplica al service role).
-- Los jobs insertan con ON CONFLICT DO NOTHING, por lo que nunca intentan UPDATE.
create or replace function public.prevent_mutation()
returns trigger language plpgsql as $$
begin
  raise exception 'Tabla append-only: % no permitido en %', TG_OP, TG_TABLE_NAME
    using errcode = 'check_violation';
end;
$$;

drop trigger if exists predictions_append_only on public.predictions;
create trigger predictions_append_only
  before update or delete on public.predictions
  for each row execute function public.prevent_mutation();

drop trigger if exists pit_snapshots_append_only on public.pit_snapshots;
create trigger pit_snapshots_append_only
  before update or delete on public.pit_snapshots
  for each row execute function public.prevent_mutation();

drop trigger if exists prediction_outcomes_append_only on public.prediction_outcomes;
create trigger prediction_outcomes_append_only
  before update or delete on public.prediction_outcomes
  for each row execute function public.prevent_mutation();

-- Nota RLS/permisos: las tablas tienen RLS activo y SOLO policy de SELECT para
-- 'authenticated'. Sin policies de INSERT/UPDATE/DELETE, los roles anon/authenticated no
-- pueden escribir. El service role (jobs) escribe saltando RLS, pero los triggers de
-- arriba le impiden modificar o borrar: solo puede INSERTAR. Append-only garantizado.
