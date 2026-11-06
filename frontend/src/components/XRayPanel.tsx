import { useEffect, useMemo, useState } from "react";
import { Panel } from "./Panel";
import { getXrayData, type XraySnapshot } from "../data";
import { effectiveExposure, type EtfWeight, type PortfolioHolding } from "../core/xray";
import { HoldingsImport } from "./HoldingsImport";
import { money } from "../format";

const COMMODITY_ETFS = ["GLD", "SLV", "IAU", "PPLT", "PALL", "SGOL", "SIVR"];
const PROVIDER_LABEL: Record<string, string> = {
  nport: "SEC N-PORT", ssga: "State Street", invesco: "Invesco", vanguard: "Vanguard",
  commodity: "Materia prima", manual: "Importación manual",
};

function Tile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-term-border bg-term-panel2 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-term-muted">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold tabnum ${tone ?? "text-term-fg"}`}>{value}</div>
    </div>
  );
}

export function XRayPanel({ holdings, valuationAsOf }:
  { holdings: PortfolioHolding[]; valuationAsOf?: string | null }) {
  const [snapshots, setSnapshots] = useState<XraySnapshot[]>([]);
  const [weights, setWeights] = useState<EtfWeight[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const [sel, setSel] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const etfs = useMemo(() => holdings.filter((h) => h.isEtf).map((h) => h.ticker.toUpperCase()), [holdings]);
  const etfValue = useMemo(() => {
    const m: Record<string, number> = {};
    for (const h of holdings) if (h.isEtf) m[h.ticker.toUpperCase()] = h.valueUsd;
    return m;
  }, [holdings]);

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
  }, [etfs.join(","), reloadKey]);

  const xray = useMemo(() => effectiveExposure(holdings, weights), [holdings, weights]);
  const snapByEtf = useMemo(() => Object.fromEntries(snapshots.map((s) => [s.etf, s])), [snapshots]);
  const commodityUsd = useMemo(() => holdings
    .filter((h) => h.isEtf && COMMODITY_ETFS.includes(h.ticker.toUpperCase()))
    .reduce((s, h) => s + h.valueUsd, 0), [holdings]);
  const otherUnknownUsd = Math.max(0, xray.unknownUsd - commodityUsd);
  const coveredEtfs = new Set(snapshots.map((s) => s.etf));
  const pending = etfs.filter((e) => !coveredEtfs.has(e));

  const sectorConc = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of xray.byCompany) {
      const sec = c.sector || "Sin clasificar";
      m.set(sec, (m.get(sec) ?? 0) + c.total);
    }
    return [...m.entries()].map(([sector, usd]) => ({ sector, usd })).sort((a, b) => b.usd - a.usd);
  }, [xray]);

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
  if (loading) return <Panel title="Portfolio X-Ray · Exposición Real"><div className="h-24 animate-pulse rounded bg-term-panel2" /></Panel>;

  const top = showAll ? xray.byCompany.slice(0, 20) : xray.byCompany.slice(0, 10);
  const selected = sel ? xray.byCompany.find((c) => c.ticker === sel) : null;
  const pctOf = (v: number) => xray.totalUsd > 0 ? v / xray.totalUsd : 0;
  const positionsUsd = holdings.reduce((s, h) => s + h.valueUsd, 0);
  const sectorKnownPct = sectorConc.filter((s) => s.sector !== "Sin clasificar").reduce((s, x) => s + x.usd, 0) / (xray.identifiedUsd || 1);

  return (
    <Panel title="Portfolio X-Ray · Exposición Real">
      {/* Resumen premium */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile label="Valor cartera" value={money(xray.totalUsd)} />
        <Tile label="En empresas" value={`${(xray.identifiedPct * 100).toFixed(1)}%`} tone="text-term-good" />
        <Tile label="Materias primas" value={money(commodityUsd)} />
        <Tile label="Efectivo/otros/no identif." value={money(otherUnknownUsd)} tone="text-term-warn" />
      </div>
      {pending.length > 0 && <p className="mt-2 text-xs text-term-warn">Pendientes de cobertura: {pending.join(", ")}</p>}

      {/* Trazabilidad por ETF */}
      <div className="mt-4">
        <h4 className="mb-1 text-xs uppercase text-term-muted">Trazabilidad de composiciones</h4>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead><tr className="text-left text-xs uppercase text-term-muted">
              <th className="py-1">ETF</th><th>Fuente</th><th>Composición</th>
              <th className="text-right">Líneas</th><th className="text-right">Cobertura</th><th>Estado</th></tr></thead>
            <tbody>
              {etfs.map((e) => {
                const s = snapByEtf[e];
                return (
                  <tr key={e} className="border-b border-term-border last:border-0">
                    <td className="py-1.5 font-mono font-semibold">{e}</td>
                    <td className="text-term-muted">{s ? (PROVIDER_LABEL[s.provider] ?? s.provider) : "—"}</td>
                    <td className="tabnum">{s?.as_of ?? <span className="text-term-warn">sin datos</span>}</td>
                    <td className="text-right tabnum">{s?.n_lines ?? "—"}</td>
                    <td className="text-right tabnum">{s?.weight_sum != null ? `${(s.weight_sum * 100).toFixed(1)}%` : "—"}</td>
                    <td>{s
                      ? <span className="rounded bg-term-good/15 px-1.5 py-0.5 text-xs text-term-good">{s.status}{s.source === "manual" ? " · manual" : ""}</span>
                      : <span className="rounded bg-term-panel2 px-1.5 py-0.5 text-xs text-term-warn">pendiente</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-1 text-[11px] text-term-faint">
          <b>Composición</b> = fecha del snapshot de holdings (SEC N-PORT, con rezago mensual).
          <b> Valoración</b> = precios de mercado actuales{valuationAsOf ? ` (${valuationAsOf})` : ""}. Son fechas distintas.
        </p>
      </div>

      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        {/* Exposición por empresa */}
        <div>
          <div className="mb-1 flex items-center justify-between">
            <h4 className="text-xs uppercase text-term-muted">Exposición efectiva por empresa</h4>
            <button onClick={() => setShowAll(!showAll)} className="text-[11px] text-term-accent">{showAll ? "Top 10" : "Top 20"}</button>
          </div>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs uppercase text-term-muted">
              <th className="py-1">Empresa</th><th className="text-right">Efectiva</th>
              <th className="text-right">% cart.</th><th className="text-right">Dir/Ind</th></tr></thead>
            <tbody>
              {top.map((c) => (
                <tr key={c.ticker}
                    className={`cursor-pointer border-b border-term-border last:border-0 hover:bg-term-panel2 ${sel === c.ticker ? "bg-term-panel2" : ""}`}
                    onClick={() => setSel(sel === c.ticker ? null : c.ticker)}>
                  <td className="py-1.5"><span className="font-mono font-semibold">{c.ticker}</span>
                    <div className="truncate text-[10px] text-term-faint" style={{ maxWidth: 160 }}>{c.name ?? ""}</div></td>
                  <td className="text-right tabnum">{money(c.total)}</td>
                  <td className="text-right tabnum">{(pctOf(c.total) * 100).toFixed(1)}%</td>
                  <td className="text-right tabnum text-[11px] text-term-faint">{c.total > 0 ? `${Math.round((c.direct / c.total) * 100)}/${Math.round((c.indirect / c.total) * 100)}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {selected && (
            <div className="mt-2 rounded-lg border border-term-border bg-term-panel2 p-3 text-sm">
              <div className="mb-1 font-semibold">{selected.name ?? selected.ticker} <span className="font-mono text-term-faint">{selected.ticker}</span></div>
              <div className="text-xs text-term-muted">Exposición efectiva total: <b className="text-term-fg">{money(selected.total)}</b> ({(pctOf(selected.total) * 100).toFixed(1)}% de la cartera){selected.sector ? ` · ${selected.sector}` : ""}</div>
              <table className="mt-1.5 w-full text-xs">
                <tbody>
                  {selected.sources.sort((a, b) => b.amount - a.amount).map((s) => {
                    const isDirect = s.via === "directo";
                    const w = !isDirect && etfValue[s.via] ? s.amount / etfValue[s.via] : null;
                    const d = !isDirect ? snapByEtf[s.via]?.as_of : null;
                    return (
                      <tr key={s.via} className="border-b border-term-border last:border-0">
                        <td className="py-1">{isDirect ? "Posición directa" : `vía ${s.via}`}</td>
                        <td className="text-right tabnum">{money(s.amount)}</td>
                        <td className="text-right tabnum text-term-faint">{w != null ? `peso ${(w * 100).toFixed(2)}%` : ""}</td>
                        <td className="text-right tabnum text-term-faint">{d ?? ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Sector + solapamiento */}
        <div className="grid gap-5">
          <div>
            <div className="mb-1 flex items-center justify-between">
              <h4 className="text-xs uppercase text-term-muted">Concentración por sector</h4>
              <span className="text-[10px] text-term-faint">{(sectorKnownPct * 100).toFixed(0)}% clasificado</span>
            </div>
            {sectorConc.slice(0, 9).map((s) => (
              <div key={s.sector} className="mb-1">
                <div className="flex justify-between text-xs">
                  <span className={s.sector === "Sin clasificar" ? "text-term-faint" : ""}>{s.sector}</span>
                  <span className="tabnum">{(pctOf(s.usd) * 100).toFixed(1)}%</span></div>
                <div className="h-1.5 w-full rounded bg-term-panel2"><div className={`h-full rounded ${s.sector === "Sin clasificar" ? "bg-term-faint" : "bg-term-accent"}`} style={{ width: `${Math.min(100, pctOf(s.usd) * 100)}%` }} /></div>
              </div>
            ))}
          </div>
          <div>
            <h4 className="mb-1 text-xs uppercase text-term-muted">Solapamiento entre ETFs</h4>
            {overlaps.length === 0 ? <p className="text-xs text-term-faint">Sin solapamiento calculable.</p> : (
              <table className="w-full text-sm">
                <tbody>
                  {overlaps.slice(0, 6).map((o) => (
                    <tr key={o.a + o.b} className="border-b border-term-border last:border-0">
                      <td className="py-1 font-mono text-xs">{o.a} ∩ {o.b}</td>
                      <td className="text-right tabnum text-xs">{(o.overlap * 100).toFixed(1)}% · {o.shared} empresas</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="mt-1 text-[10px] text-term-faint">
              Solapamiento = Σ mín(peso en A, peso en B) sobre empresas comunes. Denominador = 100% del fondo;
              es la fracción idéntica entre ambos ETFs, <b>ponderada por peso</b> (no por nº de empresas), más el conteo de empresas compartidas.
            </p>
          </div>
        </div>
      </div>

      {/* Conciliación */}
      <div className="mt-4 rounded-lg border border-term-border bg-term-panel2 px-3 py-2 text-xs">
        <b className="text-term-muted">Conciliación:</b>{" "}
        empresas {money(xray.identifiedUsd)} + materias primas {money(commodityUsd)} + efectivo/otros {money(otherUnknownUsd)} ={" "}
        <b className="text-term-fg">{money(xray.identifiedUsd + commodityUsd + otherUnknownUsd)}</b>{" "}
        = valor de posiciones <b className="text-term-fg">{money(positionsUsd)}</b>{" "}
        {Math.abs((xray.identifiedUsd + xray.unknownUsd) - positionsUsd) < 1 ? <span className="text-term-good">✓ sin doble conteo</span> : <span className="text-term-warn">⚠ revisar</span>}
      </div>

      <div className="mt-3"><HoldingsImport etfs={etfs} onImported={() => setReloadKey((k) => k + 1)} /></div>
      <p className="mt-2 text-[10px] text-term-faint">
        Exposición efectiva = directa + Σ(valor en ETF × peso). El valor de cada ETF se distribuye entre sus
        subyacentes (no se cuenta dos veces). Lo no identificado nunca se atribuye a empresas.
      </p>
    </Panel>
  );
}
