import { useMemo, useState } from "react";
import type { PriceBar } from "../data";
import { annualizedVol, maxDrawdown, periodReturn } from "../core/series";
import { money, pct } from "../format";

export interface ChartSeries { label: string; bars: PriceBar[]; color: string; }

const RANGES: Array<{ k: string; days: number | null }> = [
  { k: "5D", days: 5 }, { k: "1M", days: 31 }, { k: "3M", days: 92 }, { k: "6M", days: 183 },
  { k: "1A", days: 365 }, { k: "3A", days: 1095 }, { k: "5A", days: 1825 }, { k: "Máx", days: null },
];

const W = 800, H = 260, PAD = 8;

function cutoffISO(anchor: string, days: number | null): string {
  if (days === null) return "0000-01-01";
  const d = new Date(anchor);
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

// PriceChart: dibuja una o varias series (SVG), con selector de rango y comparación
// rebasada a 100. Usa cierres AJUSTADOS. Nada simulado: si no hay datos, lo dice.
export function PriceChart({ primary, benchmarks }: { primary: ChartSeries; benchmarks: ChartSeries[] }) {
  const [range, setRange] = useState("1A");
  const [compare, setCompare] = useState(false);

  const anchor = primary.bars.length ? primary.bars[primary.bars.length - 1].as_of : new Date().toISOString().slice(0, 10);
  const from = useMemo(() => cutoffISO(anchor, RANGES.find((r) => r.k === range)?.days ?? null), [anchor, range]);

  const drawn = useMemo(() => {
    const list = compare ? [primary, ...benchmarks] : [primary];
    return list.map((s) => ({ ...s, pts: s.bars.filter((b) => b.as_of >= from) }))
      .filter((s) => s.pts.length > 1);
  }, [primary, benchmarks, compare, from]);

  const primaryPts = useMemo(() => primary.bars.filter((b) => b.as_of >= from), [primary.bars, from]);

  const geom = useMemo(() => {
    if (drawn.length === 0) return null;
    const allMs = drawn.flatMap((s) => s.pts.map((p) => Date.parse(p.as_of)));
    const minMs = Math.min(...allMs), maxMs = Math.max(...allMs);
    const spanMs = maxMs - minMs || 1;
    // valores: si compara, rebasar cada serie a 100 en su inicio; si no, precio real
    const seriesVals = drawn.map((s) => {
      const base = s.pts[0].close || 1;
      return s.pts.map((p) => ({ ms: Date.parse(p.as_of), v: compare ? (p.close / base) * 100 : p.close }));
    });
    const allV = seriesVals.flat().map((p) => p.v);
    const minV = Math.min(...allV), maxV = Math.max(...allV);
    const spanV = maxV - minV || 1;
    const x = (ms: number) => PAD + ((ms - minMs) / spanMs) * (W - 2 * PAD);
    const y = (v: number) => PAD + (1 - (v - minV) / spanV) * (H - 2 * PAD);
    const paths = drawn.map((s, i) => ({
      color: s.color, label: s.label,
      d: seriesVals[i].map((p, j) => `${j === 0 ? "M" : "L"} ${x(p.ms).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" "),
    }));
    return { paths };
  }, [drawn, compare]);

  const closes = primaryPts.map((p) => p.close);
  const ret = periodReturn(closes);
  const vol = annualizedVol(closes);
  const mdd = maxDrawdown(closes);
  const last = primary.bars.length ? primary.bars[primary.bars.length - 1] : null;

  if (primary.bars.length === 0) {
    return (
      <p className="text-sm text-term-warn">
        Sin histórico todavía para {primary.label}. Se llena con el backfill del job de histórico.
      </p>
    );
  }

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-1">
        {RANGES.map((r) => (
          <button key={r.k} onClick={() => setRange(r.k)}
            className={`rounded px-2 py-0.5 text-xs ${range === r.k ? "bg-term-panel2 text-term-fg" : "text-term-muted hover:text-term-fg"}`}>
            {r.k}
          </button>
        ))}
        {benchmarks.length > 0 && (
          <button onClick={() => setCompare(!compare)}
            className={`ml-2 rounded border border-term-border px-2 py-0.5 text-xs ${compare ? "bg-term-panel2 text-term-fg" : "text-term-muted"}`}>
            {compare ? "Comparando (base 100)" : "Comparar vs S&P 500 / Nasdaq"}
          </button>
        )}
      </div>

      {geom ? (
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-56 w-full rounded-lg border border-term-border bg-term-panel2">
          {geom.paths.map((p, i) => (
            <path key={i} d={p.d} fill="none" stroke={p.color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
      ) : (
        <p className="text-sm text-term-muted">Sin datos en este rango.</p>
      )}

      {compare && (
        <div className="flex flex-wrap gap-3 text-[11px]">
          {drawn.map((s) => (
            <span key={s.label} className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color }} />{s.label}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-term-muted">
        {last && <span>Último: <b className="text-term-fg tabnum">{money(last.close)}</b> ({last.as_of})</span>}
        <span>Retorno {range}: <b className={ret !== null && ret >= 0 ? "text-term-good" : "text-term-crit"}>{pct(ret)}</b></span>
        <span>Volatilidad anualizada: <b className="text-term-fg">{pct(vol)}</b></span>
        <span>Máx drawdown: <b className="text-term-crit">{pct(mdd)}</b></span>
        <span className="text-term-faint">precios ajustados por splits y distribuciones</span>
      </div>
    </div>
  );
}
