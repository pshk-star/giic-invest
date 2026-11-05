// Analítica de cartera en el navegador: port fiel de backend/app/core/portfolio.py.
// Se calcula sobre precios cacheados en Supabase (actualizados por el job diario).
// El scanner (pesado) corre en el job; esto es ligero e interactivo.
// Las fórmulas replican exactamente las del núcleo Python (ver analytics.test.ts).

export interface Position {
  ticker: string;
  name: string;
  asset_class: string; // 'equity' | 'etf'
  sector: string | null;
  country: string;
  currency: string;
  quantity: number;
  avg_cost: number;
}

export interface PriceInfo {
  close: number;
  as_of: string;
  currency: string;
}

export interface ETFHolding {
  ticker: string;
  weight: number;
}

export interface PositionValuation {
  ticker: string;
  name: string;
  asset_class: string;
  sector: string | null;
  country: string;
  currency: string;
  quantity: number;
  price: number | null;
  market_value: number | null;
  cost_basis: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  weight: number | null;
}

export interface Valuation {
  total_market_value: number;
  positions: PositionValuation[];
  missing_prices: string[];
}

export function valuation(
  positions: Position[],
  prices: Record<string, PriceInfo>,
  fx: Record<string, number> = {}
): Valuation {
  const rows: PositionValuation[] = [];
  const missing: string[] = [];
  let total = 0;
  for (const p of positions) {
    const info = prices[p.ticker];
    if (!info) {
      missing.push(p.ticker);
      rows.push(blankRow(p));
      continue;
    }
    const f = p.currency === "USD" ? 1 : fx[p.currency] ?? null;
    if (f === null) {
      // sin tasa FX: no se asume 1:1, se marca como precio faltante en base
      missing.push(p.ticker);
      rows.push({ ...blankRow(p), price: info.close });
      continue;
    }
    const mv = p.quantity * info.close * f;
    const cost = p.quantity * p.avg_cost * f;
    const pnl = mv - cost;
    total += mv;
    rows.push({
      ticker: p.ticker,
      name: p.name,
      asset_class: p.asset_class,
      sector: p.sector,
      country: p.country,
      currency: p.currency,
      quantity: p.quantity,
      price: info.close,
      market_value: mv,
      cost_basis: cost,
      pnl,
      pnl_pct: cost ? pnl / cost : null,
      weight: null,
    });
  }
  for (const r of rows) if (r.market_value) r.weight = total ? r.market_value / total : 0;
  return { total_market_value: total, positions: rows, missing_prices: missing };
}

function blankRow(p: Position): PositionValuation {
  return {
    ticker: p.ticker, name: p.name, asset_class: p.asset_class, sector: p.sector,
    country: p.country, currency: p.currency, quantity: p.quantity, price: null,
    market_value: null, cost_basis: null, pnl: null, pnl_pct: null, weight: null,
  };
}

export function distribution(v: Valuation, key: "sector" | "country" | "asset_class"): Record<string, number> {
  const agg: Record<string, number> = {};
  const total = v.total_market_value || 0;
  for (const r of v.positions) {
    if (!r.market_value) continue;
    const k = (r[key] as string) || "desconocido";
    agg[k] = (agg[k] ?? 0) + r.market_value;
  }
  const out: Record<string, number> = {};
  for (const [k, val] of Object.entries(agg).sort((a, b) => b[1] - a[1])) {
    out[k] = total ? val / total : 0;
  }
  return out;
}

export interface EffectiveExposure {
  ticker: string;
  effective_value: number;
  effective_weight: number;
}

export function lookThrough(
  positions: Position[],
  prices: Record<string, PriceInfo>,
  etfHoldings: Record<string, ETFHolding[]>,
  fx: Record<string, number> = {}
): { total_market_value: number; effective_exposure: EffectiveExposure[]; coverage_warnings: { etf: string; covered_weight: number }[] } {
  const eff: Record<string, number> = {};
  const warnings: { etf: string; covered_weight: number }[] = [];
  let total = 0;
  for (const p of positions) {
    const info = prices[p.ticker];
    if (!info) continue;
    const f = p.currency === "USD" ? 1 : fx[p.currency];
    if (f === undefined) continue;
    const mv = p.quantity * info.close * f;
    total += mv;
    if (p.asset_class === "etf" && etfHoldings[p.ticker]) {
      const holdings = etfHoldings[p.ticker];
      const covered = holdings.reduce((s, h) => s + h.weight, 0);
      for (const h of holdings) eff[h.ticker] = (eff[h.ticker] ?? 0) + mv * h.weight;
      if (covered < 0.999) {
        eff[`${p.ticker}:resto`] = (eff[`${p.ticker}:resto`] ?? 0) + mv * Math.max(0, 1 - covered);
        warnings.push({ etf: p.ticker, covered_weight: Number(covered.toFixed(4)) });
      }
    } else {
      eff[p.ticker] = (eff[p.ticker] ?? 0) + mv;
    }
  }
  const rows: EffectiveExposure[] = Object.entries(eff)
    .map(([ticker, v]) => ({ ticker, effective_value: v, effective_weight: total ? v / total : 0 }))
    .sort((a, b) => b.effective_value - a.effective_value);
  return { total_market_value: total, effective_exposure: rows, coverage_warnings: warnings };
}

export function herfindahl(weights: number[]): number {
  const w = weights.filter((x) => Number.isFinite(x) && x > 0);
  const sum = w.reduce((s, x) => s + x, 0);
  if (sum <= 0) return NaN;
  const norm = w.map((x) => x / sum);
  return norm.reduce((s, x) => s + x * x, 0);
}

export function effectiveHoldings(weights: number[]): number {
  const h = herfindahl(weights);
  return h && Number.isFinite(h) && h > 0 ? 1 / h : NaN;
}

export function concentrationReport(
  lt: { effective_exposure: EffectiveExposure[] },
  maxWeightPerAsset = 0.25
) {
  const weights = lt.effective_exposure.map((r) => r.effective_weight);
  const breaches = lt.effective_exposure
    .filter((r) => r.effective_weight > maxWeightPerAsset)
    .map((r) => ({
      ticker: r.ticker,
      effective_weight: r.effective_weight,
      over_by: r.effective_weight - maxWeightPerAsset,
    }));
  return {
    hhi: herfindahl(weights),
    effective_holdings: effectiveHoldings(weights),
    top_exposure: lt.effective_exposure[0] ?? null,
    limit: maxWeightPerAsset,
    breaches,
  };
}
