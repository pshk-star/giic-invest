// Etapa A — PERFIL persistente del inversionista. Deriva los límites de decisión desde el perfil
// (configurado UNA vez en `settings`), para que los análisis corran sin parámetros manuales. Si faltan
// datos ESENCIALES, se piden explícitamente (no se inventan). Los topes prudenciales por tolerancia al
// riesgo están documentados y son revisables (no límites arbitrarios permanentes).
export interface Profile {
  baseCurrency: string | null;
  capitalAvailable: number | null;      // liquidez disponible
  monthlyContribution: number | null;   // aportes periódicos
  riskTolerance: string | null;         // conservador | moderado | agresivo
  horizonYears: number | null;
  maxWeightPerAsset: number | null;     // tope explícito del perfil (0 / null ⇒ derivar de tolerancia)
  maxWeightPerSector: number | null;
  minCash: number | null;               // efectivo mínimo a conservar
  restrictions?: string[];              // exclusiones (opcional)
}

// Bandas por tolerancia al riesgo (documentadas, revisables). Se usan solo cuando el perfil no fija el
// tope explícitamente. Mayor tolerancia ⇒ permite más concentración.
const RISK_BANDS: Record<string, { pos: number; sector: number; minMargin: number }> = {
  conservador: { pos: 0.20, sector: 0.35, minMargin: 0.15 },
  moderado: { pos: 0.30, sector: 0.45, minMargin: 0.10 },
  agresivo: { pos: 0.45, sector: 0.55, minMargin: 0.08 },
};
const DEFAULT_BAND = RISK_BANDS.moderado;

function band(riskTolerance: string | null) {
  const k = (riskTolerance ?? "").trim().toLowerCase();
  return RISK_BANDS[k] ?? DEFAULT_BAND;
}

// Constraints efectivos: topes explícitos del perfil si existen; si no, derivados de la tolerancia.
export interface DerivedConstraints {
  maxPositionWeight: number; maxSectorWeight: number; minMarginToBuy: number;
  minMarginSource: string; posSource: string; sectorSource: string;
}
export function deriveConstraints(p: Profile): DerivedConstraints {
  const b = band(p.riskTolerance);
  const posSet = p.maxWeightPerAsset && p.maxWeightPerAsset > 0;
  const secSet = p.maxWeightPerSector && p.maxWeightPerSector > 0;
  return {
    maxPositionWeight: posSet ? (p.maxWeightPerAsset as number) : b.pos,
    maxSectorWeight: secSet ? (p.maxWeightPerSector as number) : b.sector,
    minMarginToBuy: b.minMargin,       // metodológico (margen de seguridad), por tolerancia
    posSource: posSet ? "perfil" : `tolerancia ${p.riskTolerance ?? "moderado"}`,
    sectorSource: secSet ? "perfil" : `tolerancia ${p.riskTolerance ?? "moderado"}`,
    minMarginSource: `tolerancia ${p.riskTolerance ?? "moderado"}`,
  };
}

// Capital a asignar: aporte mensual si está definido; si no, el capital disponible por encima del
// efectivo mínimo. Nunca negativo.
export function investableAmount(p: Profile): number {
  if (p.monthlyContribution && p.monthlyContribution > 0) return p.monthlyContribution;
  const avail = (p.capitalAvailable ?? 0) - (p.minCash ?? 0);
  return Math.max(0, avail);
}

// Datos ESENCIALES sin los cuales no se puede recomendar con rigor (se piden, no se inventan).
export function missingEssentials(p: Profile | null): string[] {
  if (!p) return ["moneda base", "capital disponible", "tolerancia al riesgo"];
  const m: string[] = [];
  if (!p.baseCurrency) m.push("moneda base");
  if (p.capitalAvailable == null) m.push("capital disponible");
  if (!p.riskTolerance) m.push("tolerancia al riesgo");
  return m;
}

export function profileFromSettings(s: Partial<{
  base_currency: string; capital_available: number; monthly_contribution: number; risk_tolerance: string;
  horizon_years: number; max_weight_per_asset: number; max_weight_per_sector: number; min_cash: number;
}> | null): Profile {
  return {
    baseCurrency: s?.base_currency ?? null,
    capitalAvailable: s?.capital_available ?? null,
    monthlyContribution: s?.monthly_contribution ?? null,
    riskTolerance: s?.risk_tolerance ?? null,
    horizonYears: s?.horizon_years ?? null,
    maxWeightPerAsset: s?.max_weight_per_asset ?? null,
    maxWeightPerSector: s?.max_weight_per_sector ?? null,
    minCash: s?.min_cash ?? null,
  };
}
