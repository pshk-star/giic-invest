-- Migración 0012 — Identidad global de instrumentos (Fase 2).
-- APROBADA por Pablo (2026-11-06) con controles. ADITIVA y COMPATIBLE: solo agrega
-- columnas nullable a public.instruments; NO borra ni modifica datos históricos, NO
-- toca transactions ni las 309 predicciones A/B/C. Idempotente (IF NOT EXISTS).
--
-- Definición de monedas (sin ambigüedad ni doble conversión):
--   currency        : alias heredado = moneda de COTIZACIÓN (ya existía; se conserva).
--   quote_currency  : moneda en la que COTIZA el instrumento (precio de mercado).
--   report_currency : moneda de los ESTADOS FINANCIEROS (fundamentales).
-- El precio de mercado ya está en quote_currency: NO se reconvierte. Las cifras de
-- estados financieros están en report_currency y solo se convierten a USD para ratios
-- que mezclan precio (quote) con fundamentales (report), una sola vez.

alter table public.instruments
  add column if not exists country         text,      -- país de cotización (ISO-3166-1 alfa-2); null si no se resuelve
  add column if not exists quote_currency  text,      -- moneda de cotización
  add column if not exists report_currency text,      -- moneda de los estados financieros
  add column if not exists instrument_type text,      -- stock | adr | gdr | etf | commodity_etf | reit | cash | unknown
  add column if not exists adr_ratio        numeric,  -- acciones ordinarias por ADR/GDR; null si no aplica o no verificado
  add column if not exists cik              text,     -- SEC Central Index Key
  add column if not exists isin             text,
  add column if not exists figi             text,
  add column if not exists lei              text,
  add column if not exists identity         jsonb,    -- por identificador: {value, source, as_of, status}
  add column if not exists identity_as_of   date;     -- fecha de la última resolución de identidad

comment on column public.instruments.quote_currency  is 'Moneda de cotización (precio de mercado). No reconvertir el precio.';
comment on column public.instruments.report_currency is 'Moneda de los estados financieros (fundamentales).';
comment on column public.instruments.currency        is 'Alias heredado = quote_currency (compatibilidad).';
comment on column public.instruments.identity        is 'jsonb con {cik,isin,figi,lei,adr_relation} cada uno {value,source,as_of,status}. status: verified|seed|derived|unavailable|not_applicable. No se inventan identificadores.';

-- Las políticas RLS existentes de instruments siguen vigentes (SELECT autenticado,
-- escritura por service role). No se redefinen aquí.

-- ============================================================================
-- ROLLBACK (NO EJECUTAR salvo que se decida revertir). Solo elimina lo agregado;
-- las columnas previas (ticker, name, asset_class, exchange, currency, sector,
-- status, source, updated_at) y todos los datos permanecen intactos.
-- ----------------------------------------------------------------------------
-- alter table public.instruments
--   drop column if exists country,
--   drop column if exists quote_currency,
--   drop column if exists report_currency,
--   drop column if exists instrument_type,
--   drop column if exists adr_ratio,
--   drop column if exists cik,
--   drop column if exists isin,
--   drop column if exists figi,
--   drop column if exists lei,
--   drop column if exists identity,
--   drop column if exists identity_as_of;
-- ============================================================================
