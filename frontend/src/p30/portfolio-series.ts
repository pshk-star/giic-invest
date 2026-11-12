// P3.0 — Serie de valor de cartera para el gráfico de evolución (PURO, testeable). No crea lógica
// financiera nueva: multiplica la tenencia ACTUAL (qty) por el precio histórico real de cada ticker,
// alineado por fecha sin look-ahead. Es "evolución a composición actual" (se etiqueta así en la UI);
// no reconstruye el histórico de transacciones. Si faltan precios, el punto se omite (no se inventa).
export interface Holding { ticker: string; qty: number }
export interface Bar { as_of: string; close: number }
export interface SeriesPoint { as_of: string; value: number }

function priceAsOf(bars: Bar[] | undefined, date: string): number | null {
  if (!bars || !bars.length) return null;
  let out: number | null = null;
  for (const b of bars) { if (b.as_of <= date) out = b.close; else break; }
  return out;
}

function addMonths(iso: string, months: number): string {
  const d = new Date(iso + "T00:00:00Z");
  const dd = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + months, d.getUTCDate()));
  return dd.toISOString().slice(0, 10);
}

// Serie de valor total por fecha (orden ascendente), submuestreada a maxPoints (conserva el último).
export function portfolioSeries(holdings: Holding[], history: Record<string, Bar[]>, maxPoints = 26): SeriesPoint[] {
  const held = holdings.filter((h) => h.qty > 0 && history[h.ticker]?.length);
  if (!held.length) return [];
  const dateSet = new Set<string>();
  for (const h of held) for (const b of history[h.ticker]) dateSet.add(b.as_of);
  const dates = [...dateSet].sort();
  const full: SeriesPoint[] = [];
  for (const d of dates) {
    let v = 0, any = false;
    for (const h of held) { const p = priceAsOf(history[h.ticker], d); if (p != null) { v += h.qty * p; any = true; } }
    if (any) full.push({ as_of: d, value: Number(v.toFixed(2)) });
  }
  if (full.length <= maxPoints) return full;
  const step = (full.length - 1) / (maxPoints - 1);
  const out: SeriesPoint[] = [];
  for (let i = 0; i < maxPoints; i++) out.push(full[Math.round(i * step)]);
  return out;
}

// Retorno del periodo (últimos N meses) sobre la serie. null si no hay historia suficiente o base inválida.
export function periodReturn(series: SeriesPoint[], months: number): number | null {
  if (series.length < 2) return null;
  const last = series[series.length - 1];
  const target = addMonths(last.as_of, -months);
  if (series[0].as_of > target) return null;        // la serie no cubre el periodo pedido
  let base = series[0];
  for (const p of series) { if (p.as_of <= target) base = p; else break; }
  if (base.value <= 0) return null;
  return last.value / base.value - 1;
}

// Puntos para una polilínea SVG (viewBox 0..w × 0..h), con y invertida (mayor valor arriba).
export function sparkPoints(series: SeriesPoint[], w = 300, h = 90): string {
  if (series.length < 2) return "";
  const vals = series.map((p) => p.value);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  return series.map((p, i) => {
    const x = (i / (series.length - 1)) * w;
    const y = h - ((p.value - min) / span) * (h - 6) - 3;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}
