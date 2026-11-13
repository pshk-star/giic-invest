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

export type ScenarioPoint = number | { fv_usd: number | null; margen?: number | null; supuestos?: string };

// Extrae el FV escalar de un escenario, tolerando el shape objeto o número (contrato back↔front).
export function scenarioFv(x: ScenarioPoint | undefined | null): number | null {
  if (x == null) return null;
  return typeof x === "number" ? x : (x.fv_usd ?? null);
}

export interface ModelBlock {
  modelo: string;
  disponible?: boolean; // false => no disponible (NO es recomendación)
  motivo?: string;
  razones?: string[];
  fair_value_usd?: number | null;
  precio?: number | null;
  margen_seguridad_pct?: number | null;
  // Escenario: el backend motor_v2 envía objetos {fv_usd, margen, supuestos}; versiones previas enviaban
  // un número. El tipo acepta ambos (Codex P2 #13/#15) y el render extrae fv_usd de forma tolerante.
  escenarios?: {
    conservador: ScenarioPoint; base: ScenarioPoint; optimista: ScenarioPoint; rango_usd?: number[];
  };
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
  // BARRERA de seguridad: accionabilidad bloqueada por inconsistencia económica no resuelta (no altera FV).
  review_block?: boolean;
  review_reasons?: string[];
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

// #4 — un margen de seguridad POSITIVO con confianza BAJA NO debe verse como señal de compra.
// Regla: solo se colorea en verde (sugiere infravaloración) si la confianza es media/alta. Con
// confianza baja (o sin confianza), el margen se muestra NEUTRO y etiquetado "no concluyente".
export interface MarginView { cls: string; label: string; neutral: boolean }
export function marginView(marginPct: number | null | undefined, confianza?: string): MarginView {
  if (marginPct == null) return { cls: "text-term-muted", label: "—", neutral: true };
  const low = confianza === "baja" || confianza == null || confianza === "producción";
  const base = `margen seg. ${marginPct.toFixed(1)}%`;
  if (low) return { cls: "text-term-muted", label: `${base} · no concluyente (confianza ${confianza ?? "n/d"})`, neutral: true };
  if (marginPct > 0) return { cls: "text-emerald-400", label: base, neutral: false };
  return { cls: "text-rose-400", label: base, neutral: false };
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
