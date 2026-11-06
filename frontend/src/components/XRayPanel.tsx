import { useEffect, useMemo, useState } from "react";
import { Panel } from "./Panel";
import { getXrayData, type XraySnapshot } from "../data";
import { effectiveExposure, type EtfWeight, type PortfolioHolding } from "../core/xray";
import { money, num } from "../format";

// Portfolio X-Ray: exposición económica efectiva por empresa (directa + indirecta vía ETFs),
// concentración, solapamiento y cobertura. No inventa: lo no identificado se marca.
export function XRayPanel({ holdings, sectorByTicker }:
  { holdings: PortfolioHolding[]; sectorByTicker: Record<string, string | undefined> }) {
  const [snapshots, setSnapshots] = useState<XraySnapshot[]>([]);
  const [weights, setWeights] = useState<EtfWeight[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const [sel, setSel] = useState<string | null>(null);

  const etfs = useMemo(() => holdings.filter((h) => h.isEtf).map((h) => h.ticker.toUpperCase()), [holdings]);

  useEffect(() => {
    if (etfs.length === 0) { setLoading(false); return; }
    setLoading(true);
    getXrayData(etfs).then((d) => {
      setSnapshots(d.snapshots);
      setWeights(d.weights.filter((w) => w.weight != null && w.ticker).map((w) => ({
        etf: w.etf, ticker: w.ticker as string, weight: w.weight as number,
        name: w.name ?? undefined, assetClass: w.asset_class, sector: w.sector ?? undefined,
      })));
    }).catch(() => { setSnapshots([]); setWeights([]); }).finally(() => setLoading(false));
  }, [etfs.join(",")]);

  const xray = useMemo(() => effectiveExposure(holdings, weights), [holdings, weights]);
  const coveredEtfs = new Set(snapshots.map((s) => s.etf));
  const pending = etfs.filter((e) => !coveredEtfs.has(e));
  const updated = snapshots.length ? snapshots.map((s) => s.as_of).sort().slice(-1)[0] : null;

  const sectorConc = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of xray.byCompany) {
      const sec = c.sector || sectorByTicker[c.ticker] || "Sin sector";
      m.set(sec, (m.get(sec) ?? 0) + c.total);
    }
    return [...m.entries()].map(([sector, usd]) => ({ sector, usd })).sort((a, b) => b.usd - a.usd);
  }, [xray, sectorByTicker]);

  const overlaps = useMemo(() => {
    const byEtf = new Map<string, Map<string, number>>();
    for (const w of weights) {
      const e = byEtf.get(w.etf) ?? byEtf.set(w.etf, new Map()).get(w.etf)!;
      e.set(w.ticker.toUpperCase(), (e.get(w.ticker.toUpperCase()) ?? 0) + w.weight);
    }
    const es = [...byEtf.keys()];
    const out: { a: string; b: string; overlap: number; shared: number }[] = [];
    for (let i = 0; i < es.length; i++) for (let j = i + 1; j < es.length; j++) {
      const A = byEtf.get(es[i])!, B = byEtf.get(es[j])!;
      let ov = 0, shared = 0;
      for (const [tk, wa] of A) { const wb = B.get(tk); if (wb != null) { ov += Math.min(wa, wb); shared++; } }
      if (shared > 0) out.push({ a: es[i], b: es[j], overlap: ov, shared });
    }
    return out.sort((x, y) => y.overlap - x.overlap);
  }, [weights]);

  if (etfs.length === 0) return null;
  if (loading) return <Panel title="Portfolio X-Ray · Exposición Real"><div className="h-20 animate-pulse rounded bg-term-panel2" /></Panel>;

  const top = (showAll ? xray.byCompany.slice(0, 20) : xray.byCompany.slice(0, 10));
  const selected = sel ? xray.byCompany.find((c) => c.ticker === sel) : null;
  const pctOf = (v: number) => xray.totalUsd > 0 ? v / xray.totalUsd : 0;

  return (
    <Panel title="Portfolio X-Ray · Exposición Real">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-term-muted">
        <span>Identificado: <b className="text-term-good">{(xray.identifiedPct * 100).toFixed(1)}%</b></span>
        <span>Desconocido: <b className="text-term-warn">{money(xray.unknownUsd)}</b> ({((1 - xray.identifiedPct) * 100).toFixed(1)}%)</span>
        <span>Total: <b className="text-term-fg">{money(xray.totalUsd)}</b></span>
        {updated && <span>Actualizado: <b className="text-term-fg">{updated}</b></span>}
        {pending.length > 0 && <span className="text-term-warn">Pendientes de cobertura: {pending.join(", ")}</span>}
      </div>

      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-1 flex items-center justify-between">
            <h4 className="text-xs uppercase text-term-muted">Exposición efectiva por empresa</h4>
            <button onClick={() => setShowAll(!showAll)} className="text-[11px] text-term-accent">{showAll ? "Top 10" : "Top 20"}</button>
          </div>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs uppercase text-term-muted">
              <th className="py-1">Empresa</th><th className="text-right">Efectiva</th>
              <th className="text-right">% cart.</th><th className="text-right">Dir/Indir</th></tr></thead>
            <tbody>
              {top.map((c) => (
                <tr key={c.ticker}
                    className={`cursor-pointer border-b border-term-border last:border-0 hover:bg-term-panel2 ${sel === c.ticker ? "bg-term-panel2" : ""}`}
                    onClick={() => setSel(sel === c.ticker ? null : c.ticker)}>
                  <td className="py-1.5 font-mono font-semibold">{c.ticker}<span className="ml-1 text-[10px] text-term-faint">{(c.name ?? "").slice(0, 18)}</span></td>
                  <td className="text-right tabnum">{money(c.total)}</td>
                  <td className="text-right tabnum">{(pctOf(c.total) * 100).toFixed(1)}%</td>
                  <td className="text-right tabnum text-[11px] text-term-faint">{c.total > 0 ? `${Math.round((c.direct / c.total) * 100)}/${Math.round((c.indirect / c.total) * 100)}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {selected && (
            <div className="mt-2 rounded-lg border border-term-border bg-term-panel2 p-2.5 text-sm">
              <div className="mb-1 font-mono font-semibold">{selected.ticker} · origen de la exposición</div>
              {selected.sources.sort((a, b) => b.amount - a.amount).map((s) => (
                <div key={s.via} className="flex justify-between text-xs">
                  <span className="text-term-muted">{s.via === "directo" ? "Posición directa" : `vía ${s.via}`}</span>
                  <span className="tabnum">{money(s.amount)} ({(pctOf(s.amount) * 100).toFixed(1)}%)</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="grid gap-4">
          <div>
            <h4 className="mb-1 text-xs uppercase text-term-muted">Concentración por sector</h4>
            {sectorConc.slice(0, 8).map((s) => (
              <div key={s.sector} className="mb-1">
                <div className="flex justify-between text-xs"><span>{s.sector}</span><span className="tabnum">{(pctOf(s.usd) * 100).toFixed(1)}%</span></div>
                <div className="h-1.5 w-full rounded bg-term-panel2"><div className="h-full rounded bg-term-accent" style={{ width: `${Math.min(100, pctOf(s.usd) * 100)}%` }} /></div>
              </div>
            ))}
          </div>
          <div>
            <h4 className="mb-1 text-xs uppercase text-term-muted">Solapamiento entre ETFs</h4>
            {overlaps.length === 0 ? <p className="text-xs text-term-faint">Sin solapamiento calculable (un solo ETF con cobertura o sin datos).</p> : (
              <table className="w-full text-sm">
                <tbody>
                  {overlaps.slice(0, 6).map((o) => (
                    <tr key={o.a + o.b} className="border-b border-term-border last:border-0">
                      <td className="py-1 font-mono text-xs">{o.a} ∩ {o.b}</td>
                      <td className="text-right tabnum text-xs">{(o.overlap * 100).toFixed(1)}% · {o.shared} nombres</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
      <p className="mt-2 text-[10px] text-term-faint">
        Exposición efectiva = directa + Σ(valor en ETF × peso). Holdings oficiales del emisor; lo no
        identificado (efectivo/derivados/pesos faltantes) se reporta como desconocido, nunca se atribuye a acciones.
      </p>
    </Panel>
  );
}
