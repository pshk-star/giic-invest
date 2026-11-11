// P2.6 — EVALUACIÓN POSTERIOR de decisiones (puro). Evalúa una recomendación REGISTRADA a 1/3/6/12
// meses, SIN look-ahead y SIN recalcular valoraciones. Compara la asignación recomendada contra
// mantener efectivo y contra un benchmark (SPY/QQQ). Reporta retorno, volatilidad y drawdown
// realizados, y el desempeño de los seleccionados vs descartados. No inventa rendimientos: si faltan
// precios suficientes, marca el resultado como no disponible.
//
// Integridad: usa solo precios con as_of ≤ fecha de horizonte (no futuro). El precio de emisión y las
// valoraciones vienen CONGELADOS del registro (no se recalculan a posteriori). Las recomendaciones son
// SIMULADAS, nunca operaciones ejecutadas.
import type { DecisionRecord } from "./decision-record";

export interface Bar { as_of: string; close: number }
export type PriceMap = Record<string, Bar[]>;

export interface LegResult { ticker: string; weight: number; return: number | null }
export interface HorizonResult {
  months: number; targetDate: string; reached: boolean;
  allocationReturn: number | null; cashReturn: number; benchmarkReturn: number | null;
  excessVsCash: number | null; excessVsBenchmark: number | null;
  realizedVol: number | null; maxDrawdown: number | null;
  perLeg: LegResult[]; discarded: LegResult[];
  missing: string[];
}
export interface DecisionEvaluation {
  decisionId: string; emittedAt: string; benchmark: string; simulated: true;
  asOfToday: string; horizons: HorizonResult[]; note: string;
}

function addMonths(iso: string, months: number): string {
  const d = new Date(iso);
  const dd = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + months, d.getUTCDate()));
  return dd.toISOString().slice(0, 10);
}

// Última barra con as_of ≤ date (sin mirar al futuro). null si no hay ninguna ≤ date.
function priceAsOf(bars: Bar[] | undefined, date: string): number | null {
  if (!bars || !bars.length) return null;
  let out: number | null = null;
  for (const b of bars) { if (b.as_of <= date) out = b.close; else break; }
  return out;
}

// Serie de cierres en (emission, target] para vol/drawdown de la ventana.
function windowCloses(bars: Bar[] | undefined, start: string, end: string): number[] {
  if (!bars) return [];
  return bars.filter((b) => b.as_of > start && b.as_of <= end).map((b) => b.close);
}

function ret(p0: number | null, p1: number | null): number | null {
  if (p0 == null || p1 == null || p0 <= 0) return null;
  return p1 / p0 - 1;
}

function volAnnual(closes: number[]): number | null {
  if (closes.length < 3) return null;
  const r: number[] = [];
  for (let i = 1; i < closes.length; i++) if (closes[i - 1] > 0) r.push(closes[i] / closes[i - 1] - 1);
  if (r.length < 2) return null;
  const mean = r.reduce((s, x) => s + x, 0) / r.length;
  const varr = r.reduce((s, x) => s + (x - mean) ** 2, 0) / (r.length - 1);
  return Math.sqrt(varr) * Math.sqrt(252);
}

function drawdown(closes: number[]): number | null {
  if (closes.length < 2) return null;
  let peak = closes[0], mdd = 0;
  for (const c of closes) { if (c > peak) peak = c; const dd = c / peak - 1; if (dd < mdd) mdd = dd; }
  return mdd;
}

const HORIZONS = [1, 3, 6, 12];

export function evaluateDecision(rec: DecisionRecord, prices: PriceMap, today = new Date().toISOString().slice(0, 10)): DecisionEvaluation {
  const emit = rec.emittedAt.slice(0, 10);
  const legs = rec.recommendations;
  const totalAmt = legs.reduce((s, l) => s + l.amount, 0);
  const discardedTickers = rec.discardedCandidates.map((d) => d.ticker);

  const horizons: HorizonResult[] = HORIZONS.map((m) => {
    const target = addMonths(rec.emittedAt, m);
    const reached = today >= target;
    const missing: string[] = [];
    if (!reached) {
      return { months: m, targetDate: target, reached: false, allocationReturn: null, cashReturn: 0,
               benchmarkReturn: null, excessVsCash: null, excessVsBenchmark: null, realizedVol: null,
               maxDrawdown: null, perLeg: [], discarded: [], missing: ["horizonte no alcanzado"] };
    }
    // retorno por leg (precio emisión congelado → precio as_of ≤ target). Faltante ⇒ null (no inventa).
    const perLeg: LegResult[] = legs.map((l) => {
      const p0 = rec.pricesAtEmission[l.ticker] ?? priceAsOf(prices[l.ticker], emit);
      const p1 = priceAsOf(prices[l.ticker], target);
      const r = ret(p0, p1);
      if (r == null) missing.push(`sin precios para ${l.ticker}`);
      return { ticker: l.ticker, weight: totalAmt > 0 ? l.amount / totalAmt : 0, return: r };
    });
    // asignación: promedio ponderado por monto SOLO sobre legs con dato (no inventa los faltantes)
    const valid = perLeg.filter((x) => x.return != null);
    const wSum = valid.reduce((s, x) => s + x.weight, 0);
    const allocationReturn = valid.length ? valid.reduce((s, x) => s + x.weight * (x.return as number), 0) / (wSum || 1) : null;

    const bench0 = rec.pricesAtEmission[rec.benchmark] ?? priceAsOf(prices[rec.benchmark], emit);
    const benchmarkReturn = ret(bench0, priceAsOf(prices[rec.benchmark], target));
    if (benchmarkReturn == null) missing.push(`sin precios de benchmark ${rec.benchmark}`);
    const cashReturn = 0;   // mantener efectivo: 0% (no se inventa rendimiento de caja)

    const discarded: LegResult[] = discardedTickers.map((t) => {
      const r = ret(rec.pricesAtEmission[t] ?? priceAsOf(prices[t], emit), priceAsOf(prices[t], target));
      return { ticker: t, weight: 0, return: r };
    }).filter((x) => x.return != null);

    // vol/drawdown realizados de la cartera asignada (serie ponderada aproximada por legs con dato)
    const dates = (prices[rec.benchmark] ?? []).filter((b) => b.as_of > emit && b.as_of <= target).map((b) => b.as_of);
    const portCloses: number[] = dates.map((d) => {
      let acc = 0, w = 0;
      for (const l of valid) { const p = priceAsOf(prices[l.ticker], d); if (p != null) { acc += l.weight * p; w += l.weight; } }
      return w > 0 ? acc / w : NaN;
    }).filter((x) => !Number.isNaN(x));

    return {
      months: m, targetDate: target, reached: true,
      allocationReturn: allocationReturn != null ? Number(allocationReturn.toFixed(4)) : null,
      cashReturn, benchmarkReturn: benchmarkReturn != null ? Number(benchmarkReturn.toFixed(4)) : null,
      excessVsCash: allocationReturn != null ? Number((allocationReturn - cashReturn).toFixed(4)) : null,
      excessVsBenchmark: allocationReturn != null && benchmarkReturn != null ? Number((allocationReturn - benchmarkReturn).toFixed(4)) : null,
      realizedVol: volAnnual(portCloses), maxDrawdown: drawdown(portCloses),
      perLeg: perLeg.map((x) => ({ ...x, weight: Number(x.weight.toFixed(4)), return: x.return != null ? Number(x.return.toFixed(4)) : null })),
      discarded: discarded.map((x) => ({ ...x, return: x.return != null ? Number((x.return as number).toFixed(4)) : null })),
      missing: [...new Set(missing)],
    };
  });

  return {
    decisionId: rec.decisionId, emittedAt: rec.emittedAt, benchmark: rec.benchmark, simulated: true,
    asOfToday: today, horizons,
    note: "Evaluación de una recomendación SIMULADA (no ejecutada). Sin look-ahead (precios as_of ≤ horizonte); " +
          "valoraciones y precio de emisión congelados; efectivo = 0%; faltantes = no disponible (no se inventan).",
  };
}
