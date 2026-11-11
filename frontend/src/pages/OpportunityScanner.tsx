// P2.2 — Opportunity Scanner (EXPERIMENTAL, bajo feature flag VITE_FF_SCANNER). Ensambla el universo
// que GIIC ya monitorea (v_latest_scan ∪ cartera ∪ ETF), valoración (P1.9), fundamentales, riesgo
// (price_history) y look-through (X-ray), y renderiza el motor buildScanner. ALIMENTA a Advisor 3.0
// con candidatos; NO ejecuta operaciones ni reemplaza decisiones. Tres rankings separados.
import { useEffect, useMemo, useState } from "react";
import { Panel } from "../components/Panel";
import {
  getTransactions, getInstruments, getCorporateActions, getPrices, getPriceHistory,
  getFundamentalValuations, getFundamentals, getLatestScan, getXrayData,
} from "../data";
import { derivePositions } from "../core/portfolio-tx";
import {
  buildScanner, type ScanInput, type ScanCandidate, type ScanEntry, type InstrumentKind,
} from "../core/opportunity-scanner";
import type { Adv3Valuation, Adv3Position } from "../core/advisor3";
import type { CompanyValuation } from "../core/fundval";
import { money, pct, num } from "../format";

const ETF = ["etf", "fund", "etn", "mutualfund"];
const HIST_CONCURRENCY = 20;   // concurrencia de historial (sin tope de universo; evita degradar rendimiento)

// Resuelve promesas en lotes para no saturar la red al cargar el universo completo.
async function inBatches<T, R>(items: T[], size: number, fn: (x: T) => Promise<R>): Promise<R[]> {
  const out: R[] = [];
  for (let i = 0; i < items.length; i += size) out.push(...await Promise.all(items.slice(i, i + size).map(fn)));
  return out;
}

function kindOf(assetClass: string | null | undefined, sector: string | null | undefined): InstrumentKind {
  if (ETF.includes((assetClass ?? "").toLowerCase())) return "etf";
  if (/financ|bank|banco|insurance|seguro/i.test(sector ?? "")) return "banco";
  if (assetClass && !["equity", "stock", "adr", "common"].includes(assetClass.toLowerCase())) return "otro";
  return "empresa";
}

function modelMargin(cv: CompanyValuation | undefined, modelo: string): { m: number | null; c: string | null } {
  const b = cv?.modelos.find((x) => x.modelo === modelo);
  if (!b || b.disponible === false || b.margen_seguridad_pct == null) return { m: null, c: null };
  return { m: b.margen_seguridad_pct / 100, c: b.confianza ?? null };
}

export function OpportunityScanner() {
  const [raw, setRaw] = useState<ScanInput | null>(null);
  const [report, setReport] = useState<ReturnType<typeof buildScanner> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [c1, setC1] = useState(1000);
  const [c2, setC2] = useState(3000);
  const [cash, setCash] = useState(0);
  const [query, setQuery] = useState("");
  const [onlyActionable, setOnlyActionable] = useState(false);
  const [compare, setCompare] = useState<string[]>([]);

  useEffect(() => {
    (async () => {
      const txns = await getTransactions();
      const ptk = [...new Set(txns.map((t) => t.ticker.toUpperCase()))];
      const [scan, fv] = await Promise.all([getLatestScan().catch(() => []), getFundamentalValuations()]);
      // universo = cartera ∪ monitoreadas (scan completo) ∪ nombres con valoración. SIN tope artificial.
      const scanTk = scan.sort((a, b) => a.rank - b.rank).map((s) => s.ticker.toUpperCase());
      const fvTk = Object.keys(fv.resultados);
      const universe = [...new Set([...ptk, ...scanTk, ...fvTk])];
      const [instruments, prices, splits, fundamentals] = await Promise.all([
        getInstruments(universe), getPrices(universe), getCorporateActions(ptk), getFundamentals(universe),
      ]);
      const positionsAll = derivePositions(txns, prices, instruments, splits).filter((p) => (p.marketValue ?? 0) > 0);
      const held = new Set(positionsAll.map((p) => p.ticker));
      const total = positionsAll.reduce((s, p) => s + (p.marketValue ?? 0), 0);
      const cashGuess = 0; // efectivo configurable abajo; el motor lo usa para impacto sobre caja

      // histories (cartera + todo el universo), en lotes para no degradar el rendimiento
      const histTk = [...new Set([...positionsAll.map((p) => p.ticker), ...universe])];
      const histArr = await inBatches(histTk, HIST_CONCURRENCY, (t) => getPriceHistory(t).catch(() => []));
      const priceHistory: Record<string, { as_of: string; close: number }[]> = {};
      histTk.forEach((t, i) => { priceHistory[t] = histArr[i].map((b) => ({ as_of: b.as_of, close: Number(b.close) })); });

      // look-through de ETF en cartera (exposición duplicada)
      const etfHeld = positionsAll.filter((p) => ETF.includes((p.asset_class ?? "").toLowerCase())).map((p) => p.ticker);
      const xray = etfHeld.length ? await getXrayData(etfHeld).catch(() => ({ weights: [] as any[] })) : { weights: [] as any[] };
      const etfLookthrough: Record<string, Record<string, number>> = {};
      for (const w of xray.weights) {
        if (!w.ticker || w.weight == null) continue;
        const wt = w.weight > 1 ? w.weight / 100 : w.weight;   // normaliza % → fracción
        (etfLookthrough[w.etf] ??= {})[String(w.ticker).toUpperCase()] = wt;
      }

      const valuation: Record<string, Adv3Valuation> = {};
      const scanFund: Record<string, { roic?: number | null; revGrowth?: number | null; netMargin?: number | null; operatingMargin?: number | null; fcfTtm?: number | null }> = {};
      const candidates: ScanCandidate[] = [];
      const sectorOf = (t: string) => instruments[t]?.sector ?? (scan.find((s) => s.ticker.toUpperCase() === t)?.sector ?? null);
      for (const t of universe) {
        const cv = fv.resultados[t];
        const prod = modelMargin(cv, "DCF_productivo");
        const giic = modelMargin(cv, "FCFF_GIIC");
        valuation[t] = {
          productiveMargin: prod.m, productiveConfidence: prod.m != null ? "media" : null,
          fcffMargin: giic.m, fcffConfidence: (giic.c as any) ?? null, priceComparable: true,
        };
        const f = fundamentals[t] as any;
        scanFund[t] = { roic: f?.roic ?? null, revGrowth: f?.rev_growth_yoy ?? null, netMargin: f?.net_margin ?? null,
          operatingMargin: f?.operating_margin ?? null, fcfTtm: f?.fcf_ttm ?? null };
        const sector = sectorOf(t);
        const assetClass = instruments[t]?.asset_class ?? null;
        candidates.push({
          ticker: t, name: instruments[t]?.name ?? null, sector, country: null,
          currency: instruments[t]?.currency ?? null, assetClass, kind: kindOf(assetClass, sector),
          inPortfolio: held.has(t), composite: scan.find((s) => s.ticker.toUpperCase() === t)?.composite ?? null,
        });
      }
      const positions: Adv3Position[] = positionsAll.map((p) => ({
        ticker: p.ticker, name: p.name, sector: instruments[p.ticker]?.sector ?? null, country: null,
        currency: p.currency, assetClass: p.asset_class, marketValue: p.marketValue ?? 0,
        weight: total > 0 ? (p.marketValue ?? 0) / total : 0,
      }));
      const input: ScanInput = {
        candidates, valuation, fundamentals: scanFund,
        portfolio: { positions, cash: cashGuess }, priceHistory, etfLookthrough,
        contributions: [1000, 3000],
        constraints: { maxPositionWeight: 0.45, maxSectorWeight: 0.50, minMarginToBuy: 0.10 },
      };
      setRaw(input);
      setReport(buildScanner(input));
    })().catch((e) => setErr(String(e))).finally(() => setLoading(false));
  }, []);

  const r = useMemo(() => {
    if (!raw) return report;
    const contributions = [...new Set([Math.max(0, c1), Math.max(0, c2)])].sort((a, b) => a - b);
    return buildScanner({ ...raw, contributions, portfolio: { ...raw.portfolio, cash } });
  }, [raw, c1, c2, cash, report]);

  if (loading) return <div className="p-8 text-term-muted">Cargando Opportunity Scanner…</div>;
  if (err) return <div className="p-8 text-rose-400">Error: {err}</div>;
  if (!r) return <div className="p-8 text-term-muted">Sin datos de universo.</div>;

  const q = query.trim().toUpperCase();
  const match = (e: ScanEntry) => (!q || e.ticker.includes(q) || (e.name ?? "").toUpperCase().includes(q)) && (!onlyActionable || e.actionable);
  const toggleCompare = (t: string) => setCompare((xs) => xs.includes(t) ? xs.filter((x) => x !== t) : xs.length < 3 ? [...xs, t] : xs);
  const compareEntries = r.entries.filter((e) => compare.includes(e.ticker));

  const basisTone = (b: string | null) => b === "valor" ? "text-term-accent" : b === "diversificador" ? "text-term-info" : "text-term-muted";

  const EntryCard = (e: ScanEntry) => (
    <details key={e.ticker} className="rounded border border-term-border/50 px-3 py-2">
      <summary className="cursor-pointer flex items-baseline justify-between gap-2 text-sm">
        <span className="flex items-center gap-2">
          <input type="checkbox" checked={compare.includes(e.ticker)} onChange={() => toggleCompare(e.ticker)} onClick={(ev) => ev.stopPropagation()} className="accent-term-accent" />
          <strong>{e.ticker}</strong>
          <span className="text-term-muted">{e.name}</span>
          {e.inPortfolio ? <span className="text-[10px] px-1 rounded bg-term-panel2 text-term-muted">en cartera</span> : null}
          {e.actionable ? <span className={`text-[10px] px-1 rounded bg-term-panel2 ${basisTone(e.actionableBasis)}`}>accionable · {e.actionableBasis}</span> : null}
        </span>
        <span className="text-xs text-term-muted">
          {e.margin != null ? `margen ${pct(e.margin)} (${e.marginSource})` : "sin FV productivo"} · conf {e.confidence ?? "n/d"}
        </span>
      </summary>
      <div className="mt-2 text-xs space-y-2">
        <div className="grid sm:grid-cols-3 gap-2">
          <div><span className="text-term-muted">Fundamental</span><div>{e.fundamentalScore != null ? num(e.fundamentalScore, 3) : "—"}</div></div>
          <div><span className="text-term-muted">Diversificación (ΔHHI)</span><div>{e.diversificationScore != null ? num(e.diversificationScore, 4) : "—"}</div></div>
          <div><span className="text-term-muted">Desacuerdo modelos</span><div>{e.disagreement ?? "—"}</div></div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead className="text-term-muted"><tr>
              <th className="text-left">Aporte</th><th>Peso→</th><th>Δvol</th><th>Contrib. riesgo</th><th>ΔHHI</th><th>Dup. ETF</th><th>Efectivo si financia</th>
            </tr></thead>
            <tbody>
              {e.sims.map((s) => (
                <tr key={s.amount} className="text-center">
                  <td className="text-left">{money(s.amount, "USD")}</td>
                  <td>{pct(s.weightBefore)}→{pct(s.weightAfter)}</td>
                  <td className={s.deltaVol > 0 ? "text-term-warn" : "text-term-accent"}>{pct(s.deltaVol)}</td>
                  <td>{s.marginalRiskContribPct != null ? pct(s.marginalRiskContribPct) : "n/d"}</td>
                  <td className={s.deltaHhiSector > 0 ? "text-term-accent" : "text-term-muted"}>{num(s.deltaHhiSector, 4)}</td>
                  <td>{pct(s.duplicatedExposure)}</td>
                  <td className={s.exceedsCash ? "text-term-crit" : ""}>{money(s.cashIfFunded, "USD")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {e.reasons.map((m, i) => <div key={i}>• {m}</div>)}
        {e.missing.length ? <div className="text-amber-300/80">Faltante: {e.missing.join("; ")}</div> : null}
        <div className="text-term-muted">Cambiaría si: {e.whatWouldChange.join("; ")}</div>
      </div>
    </details>
  );

  return (
    <div className="p-4 md:p-6 space-y-3">
      <div className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-200">
        <strong>Opportunity Scanner — experimental</strong> (P2.2). Compara oportunidades dentro y fuera de la
        cartera sobre el universo monitoreado. <strong>Alimenta Advisor 3.0; no ejecuta operaciones ni decide.</strong>
        Solo el FV productivo con confianza habilita accionabilidad por valor; un margen positivo no es compra automática.
      </div>

      <Panel title={`Cobertura del universo · ${r.coverage.evaluated}/${r.coverage.total} evaluados · ${r.coverage.excluded} excluidos`}>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4 text-xs mb-2">
          <div><span className="text-term-muted">Empresas elegibles</span><div className="text-sm">{r.coverage.eligibleCompanies}</div></div>
          <div><span className="text-term-muted">Con FV productivo / FCFF</span><div className="text-sm">{r.coverage.withProductiveFv} / {r.coverage.withFcff}</div></div>
          <div><span className="text-term-muted">Con fundamentales / historial</span><div className="text-sm">{r.coverage.withFundamentals} / {r.coverage.withReturns}</div></div>
          <div><span className="text-term-muted">Bloqueados solo por DCF productivo</span><div className="text-sm text-term-warn">{r.coverage.blockedByProductiveVeto.count}</div></div>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px]">
          {([["accionable", "text-term-accent"], ["atractivo_no_accionable", "text-term-warn"], ["evaluable_no_atractivo", "text-term-muted"], ["no_evaluable", "text-term-crit"]] as const).map(([k, tone]) => (
            <span key={k} className={`px-2 py-0.5 rounded bg-term-panel2 ${tone}`}>{k.replace(/_/g, " ")}: {r.coverage.classification[k]}</span>
          ))}
        </div>
        {r.coverage.blockedByProductiveVeto.count ? (
          <div className="text-[11px] text-term-muted mt-2">Bloqueados por DCF antiguo (insumo P2.4): {r.coverage.blockedByProductiveVeto.tickers.join(", ")}.</div>
        ) : null}
      </Panel>

      <Panel title={`Cartera · valor ${money(r.portfolioValue, "USD")} · vol ${pct(r.baseVol)} · HHI sector ${num(r.baseHhiSector, 3)}${r.hasConcentrationProblem ? " · ⚠ concentración elevada" : ""}`}>
        <div className="flex flex-wrap gap-3 items-center text-xs">
          <label>Aporte A <input type="number" value={c1} onChange={(e) => setC1(Math.max(0, Number(e.target.value) || 0))} className="w-24 bg-term-panel2 border border-term-border rounded px-2 py-1" /></label>
          <label>Aporte B <input type="number" value={c2} onChange={(e) => setC2(Math.max(0, Number(e.target.value) || 0))} className="w-24 bg-term-panel2 border border-term-border rounded px-2 py-1" /></label>
          <label>Efectivo USD <input type="number" value={cash} onChange={(e) => setCash(Math.max(0, Number(e.target.value) || 0))} className="w-24 bg-term-panel2 border border-term-border rounded px-2 py-1" /></label>
          <label className="flex-1 min-w-[180px]">Buscar <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="ticker o nombre" className="w-40 bg-term-panel2 border border-term-border rounded px-2 py-1" /></label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={onlyActionable} onChange={(e) => setOnlyActionable(e.target.checked)} className="accent-term-accent" /> solo accionables</label>
          <span className="text-term-muted">Universo {r.universeSize} · evaluados {r.evaluated} · {r.asOf}</span>
        </div>
      </Panel>

      {compareEntries.length >= 2 ? (
        <Panel title={`Comparación de candidatos (${compareEntries.length})`}>
          <div className="overflow-x-auto text-xs">
            <table className="w-full"><thead className="text-term-muted"><tr>
              <th className="text-left">Métrica</th>{compareEntries.map((e) => <th key={e.ticker}>{e.ticker}</th>)}
            </tr></thead><tbody>
              {(([
                { label: "Margen (fuente)", fn: (e: ScanEntry) => e.margin != null ? `${pct(e.margin)} (${e.marginSource})` : "—" },
                { label: "Confianza", fn: (e: ScanEntry) => String(e.confidence ?? "n/d") },
                { label: "Score fundamental", fn: (e: ScanEntry) => e.fundamentalScore != null ? num(e.fundamentalScore, 3) : "—" },
                { label: "Diversificación ΔHHI", fn: (e: ScanEntry) => e.diversificationScore != null ? num(e.diversificationScore, 4) : "—" },
                { label: "Accionable", fn: (e: ScanEntry) => e.actionable ? (e.actionableBasis ?? "sí") : "no" },
                { label: "Δvol (aporte mayor)", fn: (e: ScanEntry) => pct(e.sims[e.sims.length - 1]?.deltaVol ?? 0) },
                { label: "Contrib. riesgo", fn: (e: ScanEntry) => { const m = e.sims[e.sims.length - 1]?.marginalRiskContribPct; return m != null ? pct(m) : "n/d"; } },
              ]) as { label: string; fn: (e: ScanEntry) => string }[]).map((row) => (
                <tr key={row.label}><td className="text-left text-term-muted">{row.label}</td>
                  {compareEntries.map((e) => <td key={e.ticker} className="text-center">{row.fn(e)}</td>)}</tr>
              ))}
            </tbody></table>
          </div>
        </Panel>
      ) : null}

      {r.rankings.map((rk) => {
        const entries = rk.entries.filter(match);
        return (
          <Panel key={rk.id} title={`${rk.label} (${entries.length})`}>
            <div className="text-[11px] text-term-muted mb-2">{rk.note}</div>
            <div className="space-y-2">{entries.length ? entries.map(EntryCard) : <div className="text-term-muted text-xs">Sin candidatos que cumplan el criterio.</div>}</div>
          </Panel>
        );
      })}

      {r.excluded.length ? (
        <Panel title={`Excluidos por datos insuficientes (${r.excluded.length})`}>
          <div className="text-xs text-term-muted space-y-1">{r.excluded.map((x) => <div key={x.ticker}>{x.ticker}: {x.reason}</div>)}</div>
        </Panel>
      ) : null}

      <Panel title="Control y procedencia">
        <ul className="text-xs text-term-muted list-disc pl-4 space-y-1">
          {r.guardrails.map((g, i) => <li key={i}>{g}</li>)}
          <li>Procedencia: {r.dataProvenance.join("; ")}.</li>
        </ul>
      </Panel>
    </div>
  );
}
