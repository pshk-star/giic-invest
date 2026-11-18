import type { CompanyValuation, FundValPayload, ModelBlock } from "./fundval";
import type { GovInput } from "./valuation-policy";

export function invalidValuation(ticker: string): CompanyValuation {
  return {ticker, ccy:"", precio:null, gT_pct:null, status:"no_valorable", modelos:[]};
}

// Rows arrive in DB identity order descending. Codex P0-A: a ticker's governing FV is scoped to the most
// recent COMPLETE run (run_kind="full"). A ticker OMITTED from that complete run is NOT resurrected from an
// older run; deliberate partial runs (e.g. 5-ticker tests) published AFTER the baseline only update their
// own tickers and never invalidate the rest. With no complete run yet, nothing governs (fail closed).
// Within the admitted window the latest row wins even if malformed/invalidated.
export function latestValuations(rows: {ticker: string; payload: unknown; id?: number}[]): FundValPayload {
  const resultados: Record<string, CompanyValuation> = {};
  const rk = (r: {payload: unknown}) => (r.payload as {run_kind?: string} | null)?.run_kind;
  const rid = (r: {payload: unknown}) => (r.payload as {run_id?: string} | null)?.run_id ?? null;
  // 1) latest complete run (rows are id-desc ⇒ first "full" seen is the most recent complete run)
  let fullRunId: string | null = null;
  for (const r of rows) { if (rk(r) === "full") { fullRunId = rid(r); break; } }
  if (fullRunId === null) return {resultados, no_calibrado_a_mercado: true};   // sin corrida completa ⇒ nada gobernante
  // 2) floor = smallest identity of that complete run; its baseline + anything published after it governs
  let floor = Infinity;
  for (const r of rows) if (rid(r) === fullRunId && typeof r.id === "number") floor = Math.min(floor, r.id);
  if (!Number.isFinite(floor)) floor = -Infinity;   // ids ausentes (tests sintéticos): no recortar por id
  // 3) latest-per-ticker within the admitted window (id ≥ floor)
  for (const r of rows) {
    if (typeof r.id === "number" && r.id < floor) continue;
    const t = r.ticker.toUpperCase();
    if (resultados[t]) continue;
    const p = r.payload as CompanyValuation | null;
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
