import { useMemo, useRef, useState } from "react";
import type { PriceBar } from "../data";
import { annualizedVol, maxDrawdown, periodReturn } from "../core/series";
import { money, num, pct } from "../format";

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

interface Pt { ms: number; v: number; close: number; as_of: string; }

// PriceChart: SVG propio (sin dependencias) con rangos, comparación rebasada a base 100,
// y crosshair + tooltip interactivos (mouse y touch). Usa cierres AJUSTADOS. Nada
// simulado: no interpola precios entre fechas sin cotización.
export function PriceChart({ primary, benchmarks }: { primary: ChartSeries; benchmarks: ChartSeries[] }) {
  const [range, setRange] = useState("1A");
  const [compare, setCompare] = useState(false);
  const [hoverMs, setHoverMs] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const anchor = primary.bars.length ? primary.bars[primary.bars.length - 1].as_of : new Date().toISOString().slice(0, 10);
  const from = useMemo(() => cutoffISO(anchor, RANGES.find((r) => r.k === range)?.days ?? null), [anchor, range]);

  const drawn = useMemo(() => {
    const list = compare ? [primary, ...benchmarks] : [primary];
    return list
      .map((s) => ({ label: s.label, color: s.color, pts0: s.bars.filter((b) => b.as_of >= from) }))
      .filter((s) => s.pts0.length > 1)
      .map((s) => {
        const base = s.pts0[0].close || 1;
        const pts: Pt[] = s.pts0.map((b) => ({ ms: Date.parse(b.as_of), v: compare ? (b.close / base) * 100 : b.close, close: b.close, as_of: b.as_of }));
        return { label: s.label, color: s.color, pts };
      });
  }, [primary, benchmarks, compare, from]);

  const geom = useMemo(() => {
    if (drawn.length === 0) return null;
    const allMs = drawn.flatMap((s) => s.pts.map((p) => p.ms));
    const allV = drawn.flatMap((s) => s.pts.map((p) => p.v));
    const minMs = Math.min(...allMs), maxMs = Math.max(...allMs), spanMs = (maxMs - minMs) || 1;
    const minV = Math.min(...allV), maxV = Math.max(...allV), spanV = (maxV - minV) || 1;
    const x = (ms: number) => PAD + ((ms - minMs) / spanMs) * (W - 2 * PAD);
    const y = (v: number) => PAD + (1 - (v - minV) / spanV) * (H - 2 * PAD);
    return { minMs, maxMs, spanMs, x, y };
  }, [drawn]);

  const paths = useMemo(() => {
    if (!geom) return [];
    return drawn.map((s) => ({
      color: s.color,
      d: s.pts.map((p, j) => `${j === 0 ? "M" : "L"} ${geom.x(p.ms).toFixed(1)} ${geom.y(p.v).toFixed(1)}`).join(" "),
    }));
  }, [drawn, geom]);

  const primaryPts = drawn.length ? drawn[0].pts : [];
  const closes = primaryPts.map((p) => p.close);
  const ret = periodReturn(closes);
  const vol = annualizedVol(closes);
  const mdd = maxDrawdown(closes);
  const last = primary.bars.length ? primary.bars[primary.bars.length - 1] : null;

  // Punto más cercano por fecha dentro de una serie.
  const nearest = (pts: Pt[], ms: number): number => {
    let best = 0, bd = Infinity;
    for (let i = 0; i < pts.length; i++) {
      const d = Math.abs(pts[i].ms - ms);
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  };

  const onMove = (clientX: number) => {
    if (!geom || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    setHoverMs(geom.minMs + frac * geom.spanMs);
  };

  // Datos del tooltip en la fecha bajo el cursor.
  const hover = useMemo(() => {
    if (hoverMs === null || !geom || primaryPts.length === 0) return null;
    const pi = nearest(primaryPts, hoverMs);
    const pp = primaryPts[pi];
    const prev = pi > 0 ? primaryPts[pi - 1] : null;
    const chgUsd = prev ? pp.close - prev.close : null;
    const chgPct = prev && prev.close ? pp.close / prev.close - 1 : null;
    const rows = drawn.map((s) => {
      const idx = nearest(s.pts, pp.ms);
      return { label: s.label, color: s.color, close: s.pts[idx].close, norm: s.pts[idx].v };
    });
    return { x: geom.x(pp.ms), as_of: pp.as_of, chgUsd, chgPct, rows };
  }, [hoverMs, geom, primaryPts, drawn]);

  if (primary.bars.length === 0) {
    return <p className="text-sm text-term-warn">Sin histórico todavía para {primary.label}. Se llena con el backfill del job de histórico.</p>;
  }

  const tipLeftPct = hover ? Math.max(2, Math.min(98, (hover.x / W) * 100)) : 0;

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
        <div className="relative">
          <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
            className="h-56 w-full touch-none rounded-lg border border-term-border bg-term-panel2"
            onMouseMove={(e) => onMove(e.clientX)}
            onMouseLeave={() => setHoverMs(null)}
            onPointerDown={(e) => onMove(e.clientX)}
            onTouchMove={(e) => { if (e.touches[0]) onMove(e.touches[0].clientX); }}
            onTouchEnd={() => setHoverMs(null)}>
            {paths.map((p, i) => (
              <path key={i} d={p.d} fill="none" stroke={p.color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
            ))}
            {hover && (
              <>
                <line x1={hover.x} y1={PAD} x2={hover.x} y2={H - PAD} stroke="currentColor"
                  className="text-term-faint" strokeWidth={1} vectorEffect="non-scaling-stroke" strokeDasharray="4 3" />
                {hover.rows.map((r, i) => {
                  const idx = nearest(drawn[i].pts, Date.parse(hover.as_of));
                  return <circle key={i} cx={geom.x(drawn[i].pts[idx].ms)} cy={geom.y(drawn[i].pts[idx].v)} r={3} fill={r.color} />;
                })}
              </>
            )}
          </svg>
          {hover && (
            <div className="pointer-events-none absolute top-1 z-10 w-max max-w-[220px] -translate-x-1/2 rounded-md border border-term-border bg-term-panel px-2 py-1 text-[11px] shadow-lg"
              style={{ left: `${tipLeftPct}%` }}>
              <div className="font-semibold text-term-fg">{hover.as_of}</div>
              {hover.rows.map((r, i) => (
                <div key={i} className="flex items-center gap-1.5">
                  <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: r.color }} />
                  <span className="text-term-muted">{r.label}:</span>
                  <span className="tabnum text-term-fg">{money(r.close)}</span>
                  {compare && <span className="tabnum text-term-faint">(b100 {num(r.norm, 1)})</span>}
                </div>
              ))}
              {!compare && hover.chgUsd !== null && (
                <div className={`tabnum ${hover.chgUsd >= 0 ? "text-term-good" : "text-term-crit"}`}>
                  día: {hover.chgUsd >= 0 ? "+" : ""}{money(hover.chgUsd)} ({hover.chgPct !== null ? pct(hover.chgPct) : "—"})
                </div>
              )}
            </div>
          )}
        </div>
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
