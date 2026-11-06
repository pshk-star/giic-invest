-- 0007_pit_hardening.sql — Endurecimiento del registro point-in-time. ADITIVA e IDEMPOTENTE.
-- Requiere 0006. NO borra ni modifica predicciones existentes.
--
-- Corrige respecto del borrador previo:
--  (a) Conflicto con el UNIQUE de 0006: ese UNIQUE usaba horizon_days (días) y además era
--      NOT NULL. Se elimina ese UNIQUE y se quita el NOT NULL de horizon_days, para que
--      producción use horizon_sessions (SESIONES) sin violar restricciones.
--  (b) Unicidad backtest vs producción: el nuevo UNIQUE incluye `origin`, así una
--      predicción de backtest y una de producción con mismas claves son filas distintas.
--  (c) NULL en horizon_sessions: el UNIQUE trataría NULLs como distintos; por eso se exige
--      NOT NULL (solo si no hay filas nulas — seguro con tabla vacía; si hubiera, se deja
--      nullable y queda registrado para migración manual).
--  (d) Compatibilidad con registros existentes: columnas con DEFAULT; sin backfill
--      destructivo; horizon_days se conserva (solo deja de ser obligatorio).
--  (e) emitted_at y data_ref OBLIGATORIOS en producción: CHECK condicional por origin.
--  (f) Calendario bursátil explícito: columna `calendar` NOT NULL (default 'XNYS').
--  (g) Inmutabilidad: triggers que rechazan UPDATE/DELETE (append-only para todo rol,
--      incluido service role) + REVOKE de UPDATE/DELETE a anon/authenticated.
--  (h) RLS/seguridad: RLS sigue activo con SOLO SELECT para authenticated; sin policies
--      de escritura => anon/authenticated no pueden escribir; service role inserta.
--  (i) Idempotencia: IF NOT EXISTS, guardas por pg_constraint, CREATE OR REPLACE, triggers
--      con DROP ... IF EXISTS. Re-ejecutarla no causa error ni duplica objetos.

-- ---------- (d)(f) columnas nuevas (con DEFAULT, compatibles con filas existentes) ----------
alter table public.predictions
  add column if not exists origin           text not null default 'backtest',   -- 'backtest'|'production'
  add column if not exists emitted_at        timestamptz,                         -- fecha/hora EFECTIVA de emisión
  add column if not exists data_ref          jsonb,                               -- referencia a datos usados (versión, as_of, snapshot ids)
  add column if not exists horizon_sessions  integer,                             -- horizonte en SESIONES bursátiles
  add column if not exists calendar          text not null default 'XNYS';        -- calendario bursátil

-- ---------- (a) compatibilidad con el UNIQUE original de 0006 ----------
-- horizon_days deja de ser obligatorio (producción usará horizon_sessions).
alter table public.predictions alter column horizon_days drop not null;

-- Elimina el UNIQUE original de 0006 (el que incluye horizon_days), si existe.
do $$
declare c text;
begin
  select conname into c
    from pg_constraint
   where conrelid = 'public.predictions'::regclass and contype = 'u'
     and pg_get_constraintdef(oid) like '%horizon_days%';
  if c is not null then
    execute format('alter table public.predictions drop constraint %I', c);
  end if;
end $$;

-- ---------- (c) NOT NULL en horizon_sessions solo si es seguro ----------
do $$
begin
  if not exists (select 1 from public.predictions where horizon_sessions is null) then
    alter table public.predictions alter column horizon_sessions set not null;
  else
    raise notice 'horizon_sessions tiene NULLs: se deja nullable; requiere migración manual de esas filas.';
  end if;
end $$;

-- ---------- (e) obligatoriedad de emitted_at y data_ref en producción ----------
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'predictions_production_fields_chk') then
    alter table public.predictions add constraint predictions_production_fields_chk
      check (origin <> 'production' or (emitted_at is not null and data_ref is not null));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'predictions_origin_chk') then
    alter table public.predictions add constraint predictions_origin_chk
      check (origin in ('backtest','production'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'predictions_calendar_chk') then
    alter table public.predictions add constraint predictions_calendar_chk
      check (char_length(calendar) between 2 and 16);
  end if;
end $$;

-- ---------- (b) unicidad que separa backtest de producción, en sesiones ----------
create unique index if not exists predictions_uniq_origin
  on public.predictions (origin, model_name, model_version, ticker, as_of, horizon_sessions);

-- ---------- (g) inmutabilidad real: triggers append-only ----------
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

-- ---------- (g)(h) permisos: nadie salvo service role escribe; y nadie modifica/borra ----------
revoke update, delete on public.predictions         from anon, authenticated;
revoke update, delete on public.pit_snapshots        from anon, authenticated;
revoke update, delete on public.prediction_outcomes  from anon, authenticated;
-- (RLS ya bloquea INSERT para anon/authenticated al no existir policy de escritura.)
