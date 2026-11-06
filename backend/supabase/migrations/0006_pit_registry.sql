-- 0006_pit_registry.sql — Registro POINT-IN-TIME e inmutable para research/forecasting.
-- ADITIVA y reversible. NO altera tablas existentes.
--
-- Tres piezas, diseñadas para NO sobrescribir historia y evitar look-ahead:
--
-- 1) pit_snapshots: observaciones capturadas con sus tres fechas clave —
--    observation_date (a qué fecha se refiere el dato),
--    published_at (cuándo estuvo disponible públicamente; p.ej. fecha de filing SEC),
--    captured_at/snapshot_date (cuándo lo registramos nosotros). Append-only:
--    el job inserta con ON CONFLICT DO NOTHING (nunca actualiza).
--
-- 2) predictions: bitácora INMUTABLE de predicciones (modelo, versión, horizonte,
--    fecha de emisión, fecha de evaluación futura). ON CONFLICT DO NOTHING.
--
-- 3) prediction_outcomes: resultados posteriores en tabla SEPARADA, para que la
--    predicción original nunca se modifique.
--
-- Escritura: solo service role (jobs). Lectura: usuarios autenticados.

create table if not exists public.pit_snapshots (
  id               bigint generated always as identity primary key,
  kind             text not null,                 -- 'price'|'fundamental'|'factor'|'macro'|'signal'
  ticker           text,                           -- null para macro
  observation_date date not null,                  -- fecha a la que se refiere el valor
  published_at     date,                           -- fecha de disponibilidad pública (si se conoce)
  snapshot_date    date not null,                  -- fecha de captura (día)
  captured_at      timestamptz not null default now(),
  source           text not null,
  data_version     text,
  payload          jsonb not null,
  unique (kind, ticker, observation_date, snapshot_date)   -- dedupe; insert DO NOTHING => inmutable
);
create index if not exists pit_snapshots_lookup_idx on public.pit_snapshots (kind, ticker, observation_date);

create table if not exists public.predictions (
  id               bigint generated always as identity primary key,
  model_name       text not null,
  model_version    text not null,
  features_version text,
  ticker           text not null,
  as_of            date not null,                  -- fecha de emisión (decisión)
  horizon_days     integer not null,
  benchmark        text,
  prediction       jsonb not null,                 -- p.ej. {rel_return, prob_up, quantiles}
  uncertainty      jsonb,
  evaluate_on      date not null,                  -- as_of + horizonte
  created_at       timestamptz not null default now(),
  unique (model_name, model_version, ticker, as_of, horizon_days)  -- inmutable: DO NOTHING
);
create index if not exists predictions_eval_idx on public.predictions (evaluate_on);

create table if not exists public.prediction_outcomes (
  id               bigint generated always as identity primary key,
  prediction_id    bigint not null references public.predictions(id),
  realized_return  numeric,
  benchmark_return numeric,
  outperformed     boolean,
  detail           jsonb,
  evaluated_at     timestamptz not null default now(),
  unique (prediction_id)
);

alter table public.pit_snapshots       enable row level security;
alter table public.predictions         enable row level security;
alter table public.prediction_outcomes enable row level security;

do $$
declare t text;
begin
  foreach t in array array['pit_snapshots','predictions','prediction_outcomes']
  loop
    execute format('drop policy if exists %I_read on public.%I', t, t);
    execute format('create policy %I_read on public.%I for select to authenticated using (true)', t, t);
  end loop;
end $$;
-- Sin policies de escritura: solo el service role (jobs) escribe.
