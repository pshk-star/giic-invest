// ============================================================================
// valuation.v2.ts — MODELO EVALUABLE (NO PRODUCTIVO) — P1.4.1
// ----------------------------------------------------------------------------
// Calibración A (crecimiento por evidencia + desaceleración explícita) y
// B (normalización robusta del FCF). NO está cableado a `fairValueDCF` ni a
// Advisor 2.2. Se activa sólo tras aprobación explícita. C (CAPEX) y D (tasa)
// quedan POSPUESTOS: no se readid CAPEX de crecimiento ni se baja Ke por moat.
//
// Convención de flujo (sin cambios): OCF−CAPEX es una APROXIMACIÓN a FCFE
// (no se reetiqueta). equity = Σ VP (deuda neta NO se resta; sólo bandera).
// ============================================================================
import { DISCOUNT_BASE, sharesScaleIssue, type FundamentalsPayload, type HistoryRecord } from "./valuation";

export const V2_PARAMS = {
  // A — compresión de g1 (cóncava, asintótica): admite >18% con evidencia, sin cap plano.
  compressThreshold: 0.20,
  compressScale: 0.15,
  // A — desaceleración en dos fases: g1 → midCycle (años 1..phase1Years) → terminal.
  midCycle: 0.08,
  phase1Years: 5,
  lowGrowthBypass: 0.10, // g1 ≤ esto ⇒ fade lineal V1 (no inflar maduras)
  horizon: 10,
  // B — selección robusta de normalización.
  stableCv: 0.15,
  trendCorr: 0.60,
};

// ---------- A: crecimiento ----------
/** CAGR de ingresos SIN acotar (últimas ≤6 filas con ingresos). */
export function rawRevenueCagr(hist: HistoryRecord[]): number {
  const rows = hist.filter((h) => typeof h.revenue === "number" && (h.revenue as number) > 0).slice(-6);
  if (rows.length < 2) return 0.05;
  const first = rows[0].revenue as number, last = rows[rows.length - 1].revenue as number, n = rows.length - 1;
  if (first <= 0 || last <= 0) return 0.05;
  return Math.max(0, Math.pow(last / first, 1 / n) - 1);
}

/** Compresión cóncava: admite >18% con evidencia, comprime extremos (no cap duro ni 30% plano). */
export function g1Evidence(rawCagr: number): number {
  const { compressThreshold: T, compressScale: S } = V2_PARAMS;
  if (rawCagr <= T) return Math.max(0, rawCagr);
  return T + (rawCagr - T) / (1 + (rawCagr - T) / S);
}

/** Sendero de crecimiento con desaceleración explícita (no extrapola el CAGR 10 años). */
export function pathA(g1: number, gTerminal: number, years = V2_PARAMS.horizon): number[] {
  const out: number[] = [];
  if (g1 <= V2_PARAMS.lowGrowthBypass) {
    for (let t = 1; t <= years; t++) out.push(g1 + (gTerminal - g1) * (t - 1) / Math.max(1, years - 1));
    return out;
  }
  const gM = V2_PARAMS.midCycle, H1 = V2_PARAMS.phase1Years;
  for (let t = 1; t <= years; t++) {
    out.push(t <= H1 ? g1 + (gM - g1) * (t - 1) / Math.max(1, H1 - 1)
                     : gM + (gTerminal - gM) * (t - H1) / Math.max(1, years - H1));
  }
  return out;
}

/** DCF con sendero de crecimiento explícito. equity = Σ VP (sin restar deuda neta). */
export function runDcfPath(baseFcf: number, shares: number, path: number[], gTerminal: number, discount: number) {
  if (!(baseFcf > 0) || !(shares > 0) || !(discount > gTerminal) || path.length < 1) return null;
  let pv = 0, fcf = baseFcf;
  for (let t = 1; t <= path.length; t++) { fcf *= 1 + path[t - 1]; pv += fcf / Math.pow(1 + discount, t); }
  const tv = (fcf * (1 + gTerminal)) / (discount - gTerminal);
  const pvTerminal = tv / Math.pow(1 + discount, path.length);
  const equity = pv + pvTerminal;
  return { pvExplicit: pv, pvTerminal, equity, perShare: equity / shares, terminalWeight: pvTerminal / equity };
}

// ---------- B: normalización robusta ----------
export type NormPick = "media" | "mediana" | "reciente" | "actual";
export interface RobustNorm {
  base: number; chosen: number; pick: NormPick; why: string;
  candidates: { media: number; mediana: number; reciente: number; actual: number };
  cv: number; corr: number; years: number[]; margins: number[]; lastRev: number;
}

function mean(xs: number[]): number { return xs.reduce((s, x) => s + x, 0) / xs.length; }
function medianOf(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b); const n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}
function pearson(xs: number[], ys: number[]): number {
  const n = xs.length; if (n < 2) return 0;
  const mx = mean(xs), my = mean(ys);
  let num = 0, dx = 0, dy = 0;
  for (let i = 0; i < n; i++) { num += (xs[i] - mx) * (ys[i] - my); dx += (xs[i] - mx) ** 2; dy += (ys[i] - my) ** 2; }
  return dx > 0 && dy > 0 ? num / Math.sqrt(dx * dy) : 0;
}

/** Compara media/mediana/reciente/actual y elige por estabilidad (no por FV más alto). */
export function robustBaseFcf(hist: HistoryRecord[]): RobustNorm | null {
  const rows = hist.filter((h) => typeof h.fcf === "number" && isFinite(h.fcf as number));
  const withRev = rows.filter((h) => typeof h.revenue === "number" && (h.revenue as number) > 0);
  const recent = withRev.slice(-4);
  if (recent.length < 3) return null;
  const margins = recent.map((h) => (h.fcf as number) / (h.revenue as number));
  const years = recent.map((h) => parseInt(h.period_end.slice(0, 4), 10));
  const lastRev = withRev[withRev.length - 1].revenue as number;

  const mMean = mean(margins), mMed = medianOf(margins);
  const w = margins.map((_, i) => i + 1);
  const mRec = margins.reduce((s, m, i) => s + w[i] * m, 0) / w.reduce((s, x) => s + x, 0);
  const mCur = margins[margins.length - 1];
  const sd = Math.sqrt(mean(margins.map((m) => (m - mMean) ** 2)));
  const cv = mMean > 0 ? sd / mMean : 9;
  const corr = pearson(years, margins);

  let pick: NormPick, why: string;
  if (cv < V2_PARAMS.stableCv) { pick = "media"; why = "márgenes estables (CV<0,15)"; }
  else if (Math.abs(corr) > V2_PARAMS.trendCorr) { pick = "reciente"; why = "tendencia clara (|corr|>0,6)"; }
  else { pick = "mediana"; why = "volátil/outlier sin tendencia monótona"; }

  const cand = { media: mMean, mediana: mMed, reciente: mRec, actual: mCur };
  let chosen = cand[pick];
  chosen = Math.max(0, Math.min(chosen, Math.max(...margins))); // guarda: nunca > máx observado
  return { base: lastRev * chosen, chosen, pick, why, candidates: cand, cv, corr, years, margins, lastRev };
}

// ---------- Punto de entrada evaluable ----------
export interface FvV2Scenario { name: string; g1: number; gTerminal: number; discount: number; perShare: number; equity: number; terminalWeight: number; }
export interface FairValueV2 {
  available: boolean; reason?: string;
  rawCagr?: number; g1?: number; normalization?: RobustNorm;
  netDebtRatio?: number;            // deuda neta / equity base (bandera, NO se resta)
  scenarios?: FvV2Scenario[]; base?: FvV2Scenario;
  currency?: string;
}

/** Fair Value evaluable con A+B. NO productivo. Espejo estructural de fairValueDCF. */
export function fairValueV2(fund: FundamentalsPayload): FairValueV2 {
  const hist = (fund.history?.annual ?? []).filter((h) => h && h.period_end) as HistoryRecord[];
  const ccy = fund.history?.currency ?? fund.currency ?? "USD";
  const shares = typeof fund.diluted_shares === "number" && fund.diluted_shares > 0 ? fund.diluted_shares : null;
  if (shares === null) return { available: false, reason: "Acciones diluidas no disponibles." };
  const scaleIssue = sharesScaleIssue(shares, fund.market_cap);
  if (scaleIssue) return { available: false, reason: `${scaleIssue} No se publica Fair Value.` };
  const norm = robustBaseFcf(hist);
  if (!norm) return { available: false, reason: "Sin FCF/ingresos suficientes (≥3 años)." };
  if (!(norm.base > 0)) return { available: false, reason: "FCF base normalizado no positivo." };

  const g1 = g1Evidence(rawRevenueCagr(hist));
  const defs = [
    { name: "Conservador", gmul: 0.8, gT: 0.020, disc: DISCOUNT_BASE + 0.010 },
    { name: "Base",        gmul: 1.0, gT: 0.025, disc: DISCOUNT_BASE },
    { name: "Optimista",   gmul: 1.0, gT: 0.030, disc: DISCOUNT_BASE - 0.010 },
  ];
  const scenarios: FvV2Scenario[] = [];
  for (const d of defs) {
    const g1s = g1 * d.gmul;
    const run = runDcfPath(norm.base, shares, pathA(g1s, d.gT), d.gT, d.disc);
    if (!run) continue;
    scenarios.push({ name: d.name, g1: g1s, gTerminal: d.gT, discount: d.disc, perShare: run.perShare, equity: run.equity, terminalWeight: run.terminalWeight });
  }
  if (scenarios.length < 3) return { available: false, reason: "Supuestos inconsistentes (tasa ≤ terminal)." };
  const base = scenarios[1];

  let nd = typeof fund.net_debt === "number" ? fund.net_debt
    : (hist.length && typeof hist[hist.length - 1].net_debt === "number" ? hist[hist.length - 1].net_debt as number : 0);
  if (typeof nd !== "number" || !isFinite(nd)) nd = 0;
  const netDebtRatio = base.equity > 0 ? nd / base.equity : 0;

  return { available: true, rawCagr: rawRevenueCagr(hist), g1, normalization: norm, netDebtRatio, scenarios, base, currency: ccy };
}
