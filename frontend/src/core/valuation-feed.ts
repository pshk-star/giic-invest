import type { CompanyValuation, FundValPayload, ModelBlock } from "./fundval";
import type { GovInput } from "./valuation-policy";

export function invalidValuation(ticker: string): CompanyValuation {
  return {ticker, ccy:"", precio:null, gT_pct:null, status:"no_valorable", modelos:[]};
}

// Rows arrive in DB identity order descending. The latest row wins even if malformed
// or invalidated: never resurrect an old valuation after a failed current calculation.
export function latestValuations(rows: {ticker: string; payload: unknown}[]): FundValPayload {
  const resultados: Record<string, CompanyValuation> = {};
  for (const row of rows) {
    const t = row.ticker.toUpperCase();
    if (resultados[t]) continue;
    const p = row.payload as CompanyValuation | null;
    const valid = p && p.ticker === t && Array.isArray(p.modelos)
      && ["consistente","en_revision","no_valorable"].includes(p.status ?? "");
    resultados[t] = valid ? p : invalidValuation(t);
  }
  return {resultados, no_calibrado_a_mercado:true};
}

export function engineBlock(cv?: CompanyValuation): ModelBlock | undefined {
  return cv?.modelos?.find(m => m?.modelo === "motor_v2");
}

export function valuationInput(cv?: CompanyValuation): GovInput {
  const m = engineBlock(cv);
  const finite = typeof m?.fair_value_usd === "number" && Number.isFinite(m.fair_value_usd) && m.fair_value_usd > 0
    && typeof m.margen_seguridad_pct === "number" && Number.isFinite(m.margen_seguridad_pct);
  return {
    engineMargin: finite ? m!.margen_seguridad_pct! / 100 : null,
    engineStatus: cv?.status !== "no_valorable" && finite && m?.disponible !== false ? (m?.status ?? "no_valorable") : "no_valorable",
    engineConfidence: m?.confianza === "alta" || m?.confianza === "media" ? m.confianza : "baja",
    engineMethodologyValidated: m?.metodologia_validada === true,
    engineReason: m?.review_reasons?.join("; ") || "sin valoración gobernante admisible",
    reviewBlock: m?.review_block === true || m?.accionable === false,
    productiveMargin:null, productiveConfidence:null, priceComparable:true,
  };
}
