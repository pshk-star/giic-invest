// Métricas de series de precios — DETERMINÍSTICAS, sobre cierres AJUSTADOS.
// Devuelven null si no hay datos suficientes (nunca inventan).

export function periodReturn(closes: number[]): number | null {
  if (closes.length < 2) return null;
  const a = closes[0], b = closes[closes.length - 1];
  if (!a) return null;
  return b / a - 1;
}

// Volatilidad anualizada a partir de retornos logarítmicos diarios (×√252).
export function annualizedVol(closes: number[]): number | null {
  if (closes.length < 3) return null;
  const rets: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    if (closes[i - 1] > 0 && closes[i] > 0) rets.push(Math.log(closes[i] / closes[i - 1]));
  }
  if (rets.length < 2) return null;
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
  const variance = rets.reduce((a, b) => a + (b - mean) ** 2, 0) / (rets.length - 1);
  return Math.sqrt(variance) * Math.sqrt(252);
}

// Máximo drawdown (negativo): peor caída pico-a-valle dentro de la serie.
export function maxDrawdown(closes: number[]): number | null {
  if (closes.length < 2) return null;
  let peak = closes[0], mdd = 0;
  for (const c of closes) {
    if (c > peak) peak = c;
    if (peak > 0) mdd = Math.min(mdd, c / peak - 1);
  }
  return mdd;
}
