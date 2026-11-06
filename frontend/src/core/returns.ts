// Rentabilidad de cartera — DETERMINÍSTICA y transparente.
//  - TWR (time-weighted): rendimiento de la gestión, neutral a aportaciones/retiros.
//  - XIRR (money-weighted): rendimiento del DINERO del inversionista, sensible al timing.
// Puras, sin red. Los flujos los arma quien llama (en una moneda base coherente).

export interface CashFlow {
  date: string;   // YYYY-MM-DD
  amount: number; // salida de caja NEGATIVA (compra/aporte), entrada POSITIVA (venta/dividendo/valor final)
}

function yearsBetween(a: string, b: string): number {
  const d1 = Date.parse(a), d2 = Date.parse(b);
  return (d2 - d1) / (365.0 * 86400000);
}

function npv(rate: number, flows: CashFlow[], t0: string): number {
  let s = 0;
  for (const f of flows) s += f.amount / Math.pow(1 + rate, yearsBetween(t0, f.date));
  return s;
}

// TIR anualizada (money-weighted). Devuelve null si no hay signo mixto o no converge.
export function xirr(flows: CashFlow[]): number | null {
  if (flows.length < 2) return null;
  const sorted = [...flows].sort((a, b) => a.date.localeCompare(b.date));
  const hasNeg = sorted.some((f) => f.amount < 0);
  const hasPos = sorted.some((f) => f.amount > 0);
  if (!hasNeg || !hasPos) return null; // sin flujo de signo mixto no hay TIR
  const t0 = sorted[0].date;

  // Newton-Raphson con derivada numérica; fallback a bisección si no converge.
  let rate = 0.1;
  for (let i = 0; i < 100; i++) {
    const f = npv(rate, sorted, t0);
    const df = (npv(rate + 1e-6, sorted, t0) - f) / 1e-6;
    if (Math.abs(df) < 1e-12) break;
    const next = rate - f / df;
    if (!isFinite(next)) break;
    if (Math.abs(next - rate) < 1e-8) return next <= -1 ? null : next;
    rate = next;
  }
  // Bisección robusta en [-0.9999, 10]
  let lo = -0.9999, hi = 10.0;
  let flo = npv(lo, sorted, t0), fhi = npv(hi, sorted, t0);
  if (flo * fhi > 0) return null;
  for (let i = 0; i < 200; i++) {
    const mid = (lo + hi) / 2;
    const fm = npv(mid, sorted, t0);
    if (Math.abs(fm) < 1e-7) return mid;
    if (flo * fm < 0) { hi = mid; fhi = fm; } else { lo = mid; flo = fm; }
  }
  return (lo + hi) / 2;
}

// TWR a partir de retornos por subperiodo (encadenamiento geométrico). Neutral a flujos.
export function twr(subReturns: number[]): number {
  let g = 1;
  for (const r of subReturns) g *= (1 + r);
  return g - 1;
}

// Anualiza un retorno total dado el número de días del periodo.
export function annualize(totalReturn: number, days: number): number | null {
  if (days <= 0 || totalReturn <= -1) return null;
  return Math.pow(1 + totalReturn, 365.0 / days) - 1;
}

// Retorno simple (valor final vs costo).
export function simpleReturn(costBasis: number, marketValue: number): number | null {
  if (costBasis <= 0) return null;
  return marketValue / costBasis - 1;
}
