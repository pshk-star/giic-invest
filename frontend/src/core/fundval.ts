// P1.9 — Tipos del payload de valoración fundamental. El cálculo vive en el backend
// (app/jobs/fundamental_valuation.py); el frontend SOLO renderiza. No se duplica aritmética.
// Experimental: no sustituye el Fair Value productivo ni es recomendación.

export interface ProjYear {
  año: number;
  g_pct: number;
  margen_pct: number;
  fcff: number;
  roic_pct: number | null;
}

export interface Provenance {
  fecha: string;
  moneda: string;
  fuente?: string;
  precio_fecha?: string;
}

export interface ModelBlock {
  modelo: string;
  disponible?: boolean; // false => no disponible (NO es recomendación)
  motivo?: string;
  razones?: string[];
  fair_value_usd?: number | null;
  precio?: number | null;
  margen_seguridad_pct?: number | null;
  escenarios?: { conservador: number; base: number; optimista: number };
  confianza?: string;
  limitaciones?: string[];
  wacc_pct?: number;
  g_terminal_pct?: number;
  peso_terminal_pct?: number;
  reverse_dcf_g1_pct?: number | null;
  reinversion?: string;
  proyeccion_10a?: ProjYear[];
  procedencia?: Provenance;
  nota?: string;
}

export interface CompanyValuation {
  ticker: string;
  ccy: string;
  precio: number;
  gT_pct: number;
  modelos: ModelBlock[];
  comparacion?: { fair_values: Record<string, number>; explicacion: string };
}

export interface FundValPayload {
  "P1.9"?: string;
  generado?: string;
  no_calibrado_a_mercado?: boolean;
  resultados: Record<string, CompanyValuation>;
}

export const MODEL_LABEL: Record<string, string> = {
  DCF_productivo: "DCF productivo (actual)",
  FCFF_GIIC: "FCFF GIIC",
  FCFF_corregido: "FCFF reinversión corregida",
  FCFF_combinado_consenso: "FCFF + consenso validado",
};

export function confidenceTone(c?: string): string {
  if (c === "alta") return "text-emerald-400";
  if (c === "media") return "text-amber-400";
  if (c === "baja") return "text-rose-400";
  return "text-term-muted";
}

// Lista de modelos disponibles (con FV) para una empresa.
export function availableModels(c: CompanyValuation): ModelBlock[] {
  return c.modelos.filter((m) => m.disponible !== false && m.fair_value_usd != null);
}

// El DCF productivo es passthrough de la tubería productiva: NO experimental, NO recalculado aquí.
export function productiveBlock(c: CompanyValuation): ModelBlock | undefined {
  return c.modelos.find((m) => m.modelo === "DCF_productivo");
}

// Ningún modelo experimental debe presentarse como recomendación: validación de forma.
export function isRecommendationFree(c: CompanyValuation): boolean {
  return c.modelos.every((m) => m.modelo === "DCF_productivo" ? m.confianza === "producción"
    : (m.disponible === false || typeof m.fair_value_usd === "number"));
}
