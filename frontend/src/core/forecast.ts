// Portfolio Forecast — proyección de la cartera consolidada por SIMULACIÓN HISTÓRICA.
// Metodología: bootstrap por BLOQUES MULTIVARIANTE. Se muestrean vectores de retornos diarios
// CONJUNTOS (todos los activos del mismo día) en bloques consecutivos -> preserva correlaciones
// y autocorrelación, SIN asumir normalidad. Buy & hold (sin rebalanceo). NO usa los modelos A/B/C.
// Es una proyección basada en la distribución HISTÓRICA de retornos, no una predicción calibrada.

export interface AssetHistory {
  ticker: string;
  valueUsd: number;
  returns: number[]; // retornos diarios, ALINEADOS (misma longitud y fechas entre activos)
}

export interface HorizonResult {
  days: number; label: string;
  valP5: number; valP25: number; valP50: number; valP75: number; valP95: number; // valor USD
  retP5: number; retP50: number; retP95: number;  // retorno vs valor actual
  probLoss: number;                                // P(valor < actual)
  var95: number;                                   // pérdida en el percentil 5 (USD, negativo)
}

export interface RiskContribution { ticker: string; weightPct: number; riskPct: number; }

export interface ForecastResult {
  currentValue: number;
  annVol: number;                 // volatilidad anualizada de la cartera
  nObs: number;                   // días históricos usados
  horizons: HorizonResult[];
  riskContrib: RiskContribution[];
  hhi: number;                    // índice de concentración (0-1)
  effectiveN: number;             // número efectivo de posiciones (1/HHI)
  top5WeightPct: number;
  band: { day: number; p5: number; p50: number; p95: number }[]; // para el gráfico
  drift: "historical" | "neutral";
  warnings: string[];
}

export interface ForecastOpts {
  sims?: number; block?: number; seed?: number;
  drift?: "historical" | "neutral";  // neutral = sin deriva estimada (retornos centrados en 0)
  windowDays?: number;               // ventana histórica (últimos N retornos)
}

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function covariance(assets: AssetHistory[], n: number): number[][] {
  const k = assets.length;
  const mean = assets.map((a) => a.returns.slice(0, n).reduce((s, x) => s + x, 0) / n);
  const cov = Array.from({ length: k }, () => new Array(k).fill(0));
  for (let i = 0; i < k; i++) for (let j = i; j < k; j++) {
    let s = 0;
    for (let t = 0; t < n; t++) s += (assets[i].returns[t] - mean[i]) * (assets[j].returns[t] - mean[j]);
    cov[i][j] = cov[j][i] = s / (n - 1);
  }
  return cov;
}

function pctile(sorted: number[], q: number): number {
  if (sorted.length === 0) return 0;
  const i = Math.min(sorted.length - 1, Math.max(0, Math.floor(q * (sorted.length - 1))));
  return sorted[i];
}

const HORIZONS: [number, string][] = [[21, "1 mes"], [63, "3 meses"], [126, "6 meses"], [252, "12 meses"]];

export function forecast(assetsIn: AssetHistory[], opts?: ForecastOpts): ForecastResult {
  const sims = opts?.sims ?? 1200, block = opts?.block ?? 10, seed = opts?.seed ?? 42;
  const drift = opts?.drift ?? "historical";
  const win = opts?.windowDays ?? 0;
  const warnings: string[] = [];
  let assets = assetsIn.filter((a) => a.valueUsd > 0 && a.returns.length >= 60);
  if (win > 0) assets = assets.map((a) => ({ ...a, returns: a.returns.slice(-win) }));
  const dropped = assetsIn.length - assets.length;
  if (dropped > 0) warnings.push(`${dropped} posición(es) sin historial suficiente (≥60 días) excluidas del riesgo.`);
  const currentValue = assetsIn.reduce((s, a) => s + a.valueUsd, 0);
  const k = assets.length;
  if (k === 0) return { currentValue, annVol: 0, nObs: 0, horizons: [], riskContrib: [], hhi: 0, effectiveN: 0, top5WeightPct: 0, band: [], drift, warnings: ["Sin historial suficiente para proyectar."] };

  const n = Math.min(...assets.map((a) => a.returns.length));
  const simValue = assets.reduce((s, a) => s + a.valueUsd, 0); // valor cubierto por la simulación
  const w = assets.map((a) => a.valueUsd / simValue);

  // Volatilidad y contribución al riesgo (covarianza histórica)
  const cov = covariance(assets, n);
  const sigw = w.map((_, i) => w.reduce((s, wj, j) => s + wj * cov[i][j], 0)); // (Σw)_i
  const varP = w.reduce((s, wi, i) => s + wi * sigw[i], 0);                     // wᵀΣw (diaria)
  const annVol = Math.sqrt(Math.max(0, varP) * 252);
  const riskContrib: RiskContribution[] = assets.map((a, i) => ({
    ticker: a.ticker, weightPct: w[i] * (simValue / currentValue),
    riskPct: varP > 0 ? (w[i] * sigw[i]) / varP : 0,
  })).sort((x, y) => y.riskPct - x.riskPct);

  const sortedW = [...w].sort((a, b) => b - a);
  const hhi = w.reduce((s, x) => s + x * x, 0);
  const effectiveN = hhi > 0 ? 1 / hhi : 0;
  const top5WeightPct = sortedW.slice(0, 5).reduce((s, x) => s + x, 0) * (simValue / currentValue);

  // Retornos para la simulación: 'neutral' los centra en 0 (quita la deriva estimada),
  // conservando volatilidad y correlaciones; 'historical' usa los retornos tal cual.
  const means = assets.map((a) => a.returns.slice(0, n).reduce((s, x) => s + x, 0) / n);
  const simRets = assets.map((a, i) => a.returns.map((r) => drift === "neutral" ? r - means[i] : r));

  // Bootstrap por bloques multivariante
  const maxDays = 252;
  const rnd = mulberry32(seed);
  const cash = currentValue - simValue; // parte no simulada (se mantiene constante)
  // matriz [sim][day] del valor de cartera
  const paths: number[][] = [];
  for (let s = 0; s < sims; s++) {
    const cum = new Array(k).fill(1);
    const path = new Array(maxDays);
    let day = 0;
    while (day < maxDays) {
      // start ∈ [0, n-block] para que el bloque pueda incluir la ÚLTIMA observación
      // (índices start..start+block-1 ≤ n-1). Antes usaba (n-block), que excluía el
      // último retorno histórico. n ≥ 60 y block = 10, así que n-block+1 ≥ 51.
      const start = Math.floor(rnd() * Math.max(1, n - block + 1));
      for (let b = 0; b < block && day < maxDays; b++, day++) {
        for (let i = 0; i < k; i++) cum[i] *= (1 + simRets[i][start + b]);
        let v = cash;
        for (let i = 0; i < k; i++) v += assets[i].valueUsd * cum[i];
        path[day] = v;
      }
    }
    paths.push(path);
  }

  // Bandas por día (para el gráfico)
  const band: { day: number; p5: number; p50: number; p95: number }[] = [];
  for (let d = 0; d < maxDays; d += 5) {
    const col = paths.map((p) => p[d]).sort((a, b) => a - b);
    band.push({ day: d + 1, p5: pctile(col, 0.05), p50: pctile(col, 0.5), p95: pctile(col, 0.95) });
  }

  const horizons: HorizonResult[] = HORIZONS.map(([days, label]) => {
    const col = paths.map((p) => p[Math.min(days, maxDays) - 1]).sort((a, b) => a - b);
    const v = (q: number) => pctile(col, q);
    const probLoss = col.filter((x) => x < currentValue).length / col.length;
    return {
      days, label,
      valP5: v(0.05), valP25: v(0.25), valP50: v(0.5), valP75: v(0.75), valP95: v(0.95),
      retP5: v(0.05) / currentValue - 1, retP50: v(0.5) / currentValue - 1, retP95: v(0.95) / currentValue - 1,
      probLoss, var95: v(0.05) - currentValue,
    };
  });

  if (cash > 1) warnings.push(`${((cash / currentValue) * 100).toFixed(0)}% de la cartera sin historial (tratado como constante, 0% retorno).`);
  return { currentValue, annVol, nObs: n, horizons, riskContrib, hhi, effectiveN, top5WeightPct, band, drift, warnings };
}

// ----------------------------------------------------------------------------
// Helpers de alineación de precios -> retornos diarios conjuntos (compartidos por
// la página de Proyección y el Investment Advisor). Fechas comunes a todos los
// activos, todo el historial común disponible (cap 10 años), misma longitud entre series.
export type PriceBarLite = { as_of: string; close: number };

export function alignReturns(hist: Record<string, PriceBarLite[]>, tickers: string[]): Record<string, number[]> {
  const maps = tickers.map((t) => new Map((hist[t] ?? []).map((b) => [b.as_of, b.close])));
  let common: string[] | null = null;
  tickers.forEach((_t, i) => {
    const dates = [...maps[i].keys()];
    common = common === null ? dates : common.filter((d) => maps[i].has(d));
  });
  // Usa TODO el historial común disponible (sin corte arbitrario de ventana). El cap
  // de 10 años solo acota memoria; el modo de ventana corta vive en ForecastOpts.windowDays.
  const dates = (common ?? []).sort().slice(-2600);
  const out: Record<string, number[]> = {};
  tickers.forEach((t, i) => {
    const r: number[] = [];
    for (let k = 1; k < dates.length; k++) {
      const p0 = maps[i].get(dates[k - 1])!, p1 = maps[i].get(dates[k])!;
      if (p0 > 0 && p1 > 0) r.push(p1 / p0 - 1);
    }
    out[t] = r;
  });
  const minLen = Math.min(...tickers.map((t) => out[t].length || Infinity));
  tickers.forEach((t) => { out[t] = (out[t] ?? []).slice(-minLen); });
  return out;
}

// Construye AssetHistory[] desde un mapa de valores por ticker; opcionalmente añade
// un activo EFECTIVO (retornos 0) para reflejar liquidez dentro de la cartera.
export function buildAssets(hist: Record<string, PriceBarLite[]>, valueMap: Record<string, number>): AssetHistory[] {
  const tickers = Object.keys(valueMap).filter((t) => valueMap[t] > 0 && t !== "EFECTIVO");
  const rets = alignReturns(hist, tickers);
  const assets: AssetHistory[] = tickers.map((t) => ({ ticker: t, valueUsd: valueMap[t], returns: rets[t] ?? [] }));
  const n = Math.max(0, ...assets.map((a) => a.returns.length));
  if ((valueMap["EFECTIVO"] ?? 0) > 0) assets.push({ ticker: "EFECTIVO", valueUsd: valueMap["EFECTIVO"], returns: new Array(n).fill(0) });
  return assets;
}
