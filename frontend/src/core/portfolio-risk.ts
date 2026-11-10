// P2.1 — Motor de riesgo de portafolio en TS. ESPEJO EXACTO de app/research/portfolio_risk.py
// (parity test en portfolio-risk.test.ts contra números canónicos del motor Python). Metodología
// transparente: covarianza muestral, vol anualizada, vol de portafolio, contribución por Euler,
// drawdown, beta, HHI, exposición efectiva ETF, FX, estrés e impacto marginal. Sin recomendaciones.

export const PPY = 252;

function mean(a: number[]): number { return a.reduce((s, x) => s + x, 0) / a.length; }

export function cov(x: number[], y: number[]): number {
  const n = x.length;
  if (n < 2) return 0;
  const mx = mean(x), my = mean(y);
  let s = 0;
  for (let i = 0; i < n; i++) s += (x[i] - mx) * (y[i] - my);
  return s / (n - 1);
}

export function covMatrix(returns: Record<string, number[]>): { tickers: string[]; M: number[][] } {
  const tickers = Object.keys(returns);
  const M = tickers.map((a) => tickers.map((b) => cov(returns[a], returns[b])));
  return { tickers, M };
}

export function annualizedVol(ret: number[], ppy = PPY): number {
  if (ret.length < 2) return 0;
  return Math.sqrt(cov(ret, ret)) * Math.sqrt(ppy);
}

export function portfolioVariance(weights: number[], M: number[][]): number {
  const n = weights.length;
  let v = 0;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) v += weights[i] * weights[j] * M[i][j];
  return v;
}

export interface RiskContrib {
  volPortfolioAnnual: number;
  eulerCheck: number;
  byPosition: Record<string, { weight: number; mcr: number; contrib: number; contribPct: number }>;
}

export function riskContributions(weights: Record<string, number>, returns: Record<string, number[]>, ppy = PPY): RiskContrib {
  const tickers = Object.keys(weights).filter((t) => returns[t]);
  const w = tickers.map((t) => weights[t]);
  const M = tickers.map((a) => tickers.map((b) => cov(returns[a], returns[b])));
  const varp = portfolioVariance(w, M);
  const sig = varp > 0 ? Math.sqrt(varp) : 0;
  const byPosition: RiskContrib["byPosition"] = {};
  tickers.forEach((t, i) => {
    const mcr = sig > 0 ? w.reduce((s, _wj, j) => s + M[i][j] * w[j], 0) / sig : 0;
    const cr = w[i] * mcr;
    byPosition[t] = { weight: w[i], mcr: mcr * Math.sqrt(ppy), contrib: cr * Math.sqrt(ppy), contribPct: sig > 0 ? cr / sig : 0 };
  });
  const eulerCheck = Object.values(byPosition).reduce((s, c) => s + c.contrib, 0);
  return { volPortfolioAnnual: sig * Math.sqrt(ppy), eulerCheck, byPosition };
}

export function portfolioSeries(weights: Record<string, number>, returns: Record<string, number[]>): number[] {
  const tickers = Object.keys(weights).filter((t) => returns[t]);
  const n = tickers.length ? returns[tickers[0]].length : 0;
  const lvl = [1.0];
  for (let k = 0; k < n; k++) {
    const r = tickers.reduce((s, t) => s + weights[t] * returns[t][k], 0);
    lvl.push(lvl[lvl.length - 1] * (1 + r));
  }
  return lvl;
}

export function maxDrawdown(series: number[]): { maxDrawdown: number; peakIdx: number; troughIdx: number } {
  if (series.length < 2) return { maxDrawdown: 0, peakIdx: 0, troughIdx: 0 };
  let peak = series[0], mdd = 0, peakI = 0, troughI = 0, bestPeakI = 0;
  series.forEach((x, i) => {
    if (x > peak) { peak = x; peakI = i; }
    const dd = peak > 0 ? x / peak - 1 : 0;
    if (dd < mdd) { mdd = dd; troughI = i; bestPeakI = peakI; }
  });
  return { maxDrawdown: mdd, peakIdx: bestPeakI, troughIdx: troughI };
}

export function beta(asset: number[], bench: number[]): number | null {
  const vb = cov(bench, bench);
  return vb > 0 ? cov(asset, bench) / vb : null;
}

export function hhi(weightsByGroup: Record<string, number>): number {
  const tot = Object.values(weightsByGroup).reduce((s, w) => s + Math.abs(w), 0);
  if (tot <= 0) return 0;
  return Object.values(weightsByGroup).reduce((s, w) => s + (Math.abs(w) / tot) ** 2, 0);
}

export function concentration(weights: Record<string, number>, meta: Record<string, { sector?: string; country?: string; currency?: string }>, key: "sector" | "country" | "currency"): { hhi: number; byGroup: Record<string, number> } {
  const by: Record<string, number> = {};
  for (const [t, w] of Object.entries(weights)) {
    const g = (meta[t]?.[key]) ?? "na";
    by[g] = (by[g] ?? 0) + w;
  }
  return { hhi: hhi(by), byGroup: by };
}

export function fxExposure(weights: Record<string, number>, meta: Record<string, { currency?: string }>, base = "USD"): { byCurrency: Record<string, number>; nonBase: number } {
  const by: Record<string, number> = {};
  for (const [t, w] of Object.entries(weights)) {
    const c = meta[t]?.currency ?? base;
    by[c] = (by[c] ?? 0) + w;
  }
  const nonBase = Object.entries(by).reduce((s, [c, w]) => s + (c !== base ? w : 0), 0);
  return { byCurrency: by, nonBase };
}

// Impacto marginal: añade (+delta) o reduce (−delta) un ticker, RENORMALIZA, recomputa vol/HHI
// sobre la cartera resultante COMPLETA.
export function marginalImpact(weights: Record<string, number>, returns: Record<string, number[]>, ticker: string, delta: number, meta: Record<string, { sector?: string }>): {
  deltaVol: number; volBefore: number; volAfter: number; hhiBefore: number; hhiAfter: number; weightsAfter: Record<string, number>;
} {
  const before = riskContributions(weights, returns);
  const nw: Record<string, number> = { ...weights };
  nw[ticker] = (nw[ticker] ?? 0) + delta;
  const tot = Object.values(nw).reduce((s, x) => s + x, 0);
  if (tot > 0) for (const k of Object.keys(nw)) nw[k] = nw[k] / tot;
  const after = riskContributions(nw, returns);
  const hb = concentration(weights, meta as any, "sector").hhi;
  const ha = concentration(nw, meta as any, "sector").hhi;
  return { deltaVol: after.volPortfolioAnnual - before.volPortfolioAnnual, volBefore: before.volPortfolioAnnual, volAfter: after.volPortfolioAnnual, hhiBefore: hb, hhiAfter: ha, weightsAfter: nw };
}
