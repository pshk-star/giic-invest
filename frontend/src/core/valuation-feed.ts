import type { CompanyValuation, FundValPayload, ModelBlock } from "./fundval";
import type { GovInput } from "./valuation-policy";

import universe from "../../../backend/app/jobs/valuation_universe.json";

export const FEED_POLICY = { publicationHours: 96, priceDays: 7, financialDays: 185 } as const;
export interface ValuationRun {
  run_id: string; run_kind: string; universe_version: string;
  requested_tickers: string[]; published_at: string;
}
export interface ValuationRow { ticker: string; run_id?: string; payload: unknown; id?: number }
const DAY = 86400000;
export function invalidValuation(ticker: string, reason = "sin publicación gobernante admisible"): CompanyValuation {
  return {ticker, ccy:"", precio:null, gT_pct:null, status:"no_valorable", modelos:[{
    modelo:"motor_v2", disponible:false, status:"no_valorable", fair_value_usd:null,
    accionable:false, review_block:true, metodologia_validada:false, review_reasons:[reason],
  }]};
}
function ageOk(value: unknown, now: number, maxDays: number): boolean {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}(T.*)?$/.test(value)) return false;
  const date = Date.parse(value);
  return Number.isFinite(date) && new Date(date).toISOString().slice(0,10) === value.slice(0,10) && date <= now && now - date <= maxDays * DAY;
}
// One admitted full publication only. Partial runs are immutable diagnostics and never govern.
// No fallback to an older full run, even if the latest manifest or any of its rows is invalid.
export function latestValuations(rows: ValuationRow[], run?: ValuationRun, now = Date.now()): FundValPayload {
  const resultados: Record<string, CompanyValuation> = {};
  const blocked = (reason: string) => {
    for (const t of universe.tickers) resultados[t] = invalidValuation(t, reason);
    return {resultados, no_calibrado_a_mercado:true};
  };
  if (!run || run.run_kind !== "full" || run.universe_version !== universe.version)
    return blocked("sin corrida completa admitida");
  if (!ageOk(run.published_at, now, FEED_POLICY.publicationHours / 24))
    return blocked("publicación caducada o fecha inválida (máximo 96 horas)");
  const expected = [...universe.tickers].sort().join(",");
  if (!Array.isArray(run.requested_tickers) || [...run.requested_tickers].sort().join(",") !== expected)
    return blocked("manifiesto de cobertura incompleto");
  const admitted = rows.filter(r => r.run_id === run.run_id);
  if (admitted.length !== universe.tickers.length || admitted.map(r=>r.ticker).sort().join(",") !== expected)
    return blocked("publicación incompleta o duplicada: no se recuperan Fair Values anteriores");
  for (const row of admitted) {
    const t = row.ticker;
    const p = row.payload as CompanyValuation & {audit_inputs?: {price_date?: string}; ttm?: {fin_ttm?: string}} | null;
    if (!p || p.ticker !== t || !Array.isArray(p.modelos)
        || !["consistente","en_revision","no_valorable"].includes(p.status ?? "")) {
      resultados[t] = invalidValuation(t, "payload gobernante inválido");
    } else if (p.status !== "no_valorable" && (!ageOk(p.audit_inputs?.price_date, now, FEED_POLICY.priceDays)
               || !ageOk(p.ttm?.fin_ttm, now, FEED_POLICY.financialDays))) {
      resultados[t] = invalidValuation(t, "datos caducados, futuros o sin fecha: precio máximo 7 días; TTM máximo 185 días");
    } else {
      // A cached/admitted object also expires when reused by an Advisor calculation.
      const expiry = Math.min(Date.parse(run.published_at) + FEED_POLICY.publicationHours / 24 * DAY,
        Date.parse(p.audit_inputs?.price_date ?? "") + FEED_POLICY.priceDays * DAY,
        Date.parse(p.ttm?.fin_ttm ?? "") + FEED_POLICY.financialDays * DAY);
      resultados[t] = {...p, feed_valid_until: Number.isFinite(expiry) ? new Date(expiry).toISOString() : undefined};
    }
  }
  return {resultados, generado:run.published_at, no_calibrado_a_mercado:true};
}

// Pin the immutable run_id before loading rows. A concurrently published run cannot mix the response.
// Used by both the app and the read-only Advisor preview.
export async function readGoverningFeed(load: (table: string, params: Record<string,string>) => Promise<any[]>, now = Date.now()): Promise<FundValPayload> {
  const runs = await load("valuation_runs", {select:"run_id,run_kind,universe_version,requested_tickers,published_at", run_kind:"eq.full", order:"id.desc", limit:"1"});
  const run: ValuationRun | undefined = runs[0];
  if (!run) return latestValuations([], undefined, now);
  const rows = await load("valuation_snapshots", {select:"ticker,payload,run_id", run_id:`eq.${run.run_id}`, order:"ticker", limit:"1000"});
  return latestValuations(rows, run, now);
}

export function engineBlock(cv?: CompanyValuation): ModelBlock | undefined {
  return cv?.modelos?.find(m => m?.modelo === "motor_v2");
}

export function valuationInput(cv?: CompanyValuation, now = Date.now()): GovInput {
  if (cv?.feed_valid_until && (!Number.isFinite(Date.parse(cv.feed_valid_until)) || now > Date.parse(cv.feed_valid_until)))
    cv = invalidValuation(cv.ticker, "publicación o datos caducados desde su lectura");
  const m = engineBlock(cv);
  const finite = typeof m?.fair_value_usd === "number" && Number.isFinite(m.fair_value_usd) && m.fair_value_usd > 0
    && typeof m.margen_seguridad_pct === "number" && Number.isFinite(m.margen_seguridad_pct);
  return {
    engineValidUntil: cv?.feed_valid_until,
    engineMargin: finite ? m!.margen_seguridad_pct! / 100 : null,
    engineStatus: cv?.status !== "no_valorable" && finite && m?.disponible !== false ? (m?.status ?? "no_valorable") : "no_valorable",
    engineConfidence: m?.confianza === "alta" || m?.confianza === "media" ? m.confianza : "baja",
    engineMethodologyValidated: m?.metodologia_validada === true,
    engineReason: m?.review_reasons?.join("; ") || "sin valoración gobernante admisible",
    reviewBlock: m?.review_block === true || m?.accionable === false,
    productiveMargin:null, productiveConfidence:null, priceComparable:true,
  };
}
