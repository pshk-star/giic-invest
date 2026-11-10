// P2.1 — Advisor 3.0 (EXPERIMENTAL, bajo feature flag VITE_FF_ADVISOR3). Ensambla posiciones REALES
// (derivePositions), retornos (price_history) y valoración (P1.9) y renderiza el motor buildAdvisor3.
// Comparación con Advisor 2.2 (enlace) + simulación de asignación de capital. No ejecuta operaciones.
import { useEffect, useMemo, useState } from "react";
import { Panel } from "../components/Panel";
import {
  getTransactions, getInstruments, getCorporateActions, getPrices, getPriceHistory,
  getFundamentalValuations,
} from "../data";
import { derivePositions } from "../core/portfolio-tx";
import { buildAdvisor3, type Adv3Input, type Adv3Valuation } from "../core/advisor3";
import type { CompanyValuation, ModelBlock } from "../core/fundval";
import { money, pct, num } from "../format";

const ETF = ["etf", "fund", "etn", "mutualfund"];

function alignedReturns(hist: Record<string, { as_of: string; close: number }[]>): Record<string, number[]> {
  const maps: Record<string, Map<string, number>> = {};
  let common: Set<string> | null = null;
  for (const [t, bars] of Object.entries(hist)) {
    const m = new Map<string, number>(bars.map((b) => [b.as_of, b.close] as [string, number]));
    maps[t] = m;
    const s = new Set<string>(m.keys());
    common = common ? new Set<string>([...common].filter((d) => s.has(d))) : s;
  }
  const dates: string[] = [...(common ?? new Set<string>())].sort();
  const out: Record<string, number[]> = {};
  for (const [t, m] of Object.entries(maps)) {
    const px = dates.map((d) => m.get(d)!);
    out[t] = px.slice(1).map((p, i) => (px[i] > 0 ? p / px[i] - 1 : 0));
  }
  return out;
}

function modelMargin(cv: CompanyValuation | undefined, modelo: string): { m: number | null; c: ModelBlock["confianza"] } {
  const b = cv?.modelos.find((x) => x.modelo === modelo);
  if (!b || b.disponible === false || b.margen_seguridad_pct == null) return { m: null, c: null };
  return { m: b.margen_seguridad_pct / 100, c: b.confianza };
}

export function AdvisorComparison() {
  const [report, setReport] = useState<ReturnType<typeof buildAdvisor3> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [contribution, setContribution] = useState(3000);
  const [cash, setCash] = useState(0);
  const [raw, setRaw] = useState<Adv3Input | null>(null);

  useEffect(() => {
    (async () => {
      const txns = await getTransactions();
      const tickers = [...new Set(txns.map((t) => t.ticker.toUpperCase()))];
      const [instruments, prices, splits, fv] = await Promise.all([
        getInstruments(tickers), getPrices(tickers), getCorporateActions(tickers), getFundamentalValuations(),
      ]);
      const positions = derivePositions(txns, prices, instruments, splits).filter((p) => (p.marketValue ?? 0) > 0);
      // retornos solo para acciones con historial
      const equity = positions.filter((p) => !ETF.includes((p.asset_class ?? "").toLowerCase()));
      const histArr = await Promise.all(equity.map((p) => getPriceHistory(p.ticker)));
      const hist: Record<string, { as_of: string; close: number }[]> = {};
      equity.forEach((p, i) => { hist[p.ticker] = histArr[i].map((b) => ({ as_of: b.as_of, close: Number(b.close) })); });
      const returns = alignedReturns(hist);
      const total = positions.reduce((s, p) => s + (p.marketValue ?? 0), 0) + cash;
      const valuation: Record<string, Adv3Valuation> = {};
      const quality: Record<string, { eligible: boolean; fresh: boolean }> = {};
      for (const p of positions) {
        const cv = fv.resultados[p.ticker];
        const prod = modelMargin(cv, "DCF_productivo");
        const giic = modelMargin(cv, "FCFF_GIIC");
        valuation[p.ticker] = {
          productiveMargin: prod.m, productiveConfidence: prod.m != null ? "media" : null,
          fcffMargin: giic.m, fcffConfidence: (giic.c as any) ?? null, priceComparable: true,
        };
        quality[p.ticker] = { eligible: true, fresh: true };
      }
      const input: Adv3Input = {
        positions: positions.map((p) => ({
          ticker: p.ticker, name: p.name, sector: instruments[p.ticker]?.sector ?? null,
          country: null, currency: p.currency, assetClass: p.asset_class,
          marketValue: p.marketValue ?? 0, weight: total > 0 ? (p.marketValue ?? 0) / total : 0,
        })),
        cash, contribution, returns, valuation, quality,
        constraints: { maxPositionWeight: 0.45, maxSectorWeight: 0.50, minMarginToBuy: 0.10 },
      };
      setRaw(input);
      setReport(buildAdvisor3(input));
    })().catch((e) => setErr(String(e))).finally(() => setLoading(false));
  }, []);

  const recomputed = useMemo(() => {
    if (!raw) return null;
    return buildAdvisor3({ ...raw, contribution, cash });
  }, [raw, contribution, cash]);
  const r = recomputed ?? report;

  if (loading) return <div className="p-8 text-term-muted">Cargando Advisor 3.0…</div>;
  if (err) return <div className="p-8 text-rose-400">Error: {err}</div>;
  if (!r) return <div className="p-8 text-term-muted">Sin datos de cartera.</div>;

  const actionTone = (a: string) => a === "VENDER" ? "text-term-crit" : a === "REDUCIR" ? "text-term-warn"
    : a === "REVISAR" ? "text-term-info" : "text-term-accent";

  return (
    <div className="p-4 md:p-6 space-y-3">
      <div className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-200">
        <strong>Advisor 3.0 — experimental</strong> (P2.1). No ejecuta operaciones ni modifica inversiones.
        Mantiene Advisor 2.2 como referencia (pestaña «Investment Advisor»). El FCFF de baja confianza
        NO desplaza el Fair Value productivo; un margen positivo NO es compra automática.
      </div>

      <Panel title={`Riesgo de cartera · valor ${money(r.portfolioValue, "USD")} · efectivo ${money(r.cash, "USD")}`}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 text-sm">
          <div><div className="text-term-muted text-xs">Volatilidad anual</div><div className="text-lg font-semibold">{pct(r.risk.volAnnual)}</div></div>
          <div><div className="text-term-muted text-xs">HHI sector / país</div><div className="text-lg font-semibold">{num(r.risk.hhiSector, 3)} / {num(r.risk.hhiCountry, 3)}</div></div>
          <div><div className="text-term-muted text-xs">Exposición no-USD</div><div className="text-lg font-semibold">{pct(r.risk.fxNonBase)}</div></div>
          <div><div className="text-term-muted text-xs">Top contribuyentes de riesgo</div>
            <div className="text-xs">{r.risk.topContributors.map((c) => `${c.ticker} ${pct(c.pct)}`).join(" · ")}</div></div>
        </div>
      </Panel>

      <Panel title="Decisiones sobre posiciones existentes">
        <div className="space-y-2">
          {r.positionDecisions.map((d) => (
            <details key={d.ticker} className="rounded border border-term-border/50 px-3 py-2">
              <summary className="cursor-pointer flex items-baseline justify-between gap-2 text-sm">
                <span><strong className={actionTone(d.action)}>{d.action}</strong> · {d.ticker}</span>
                <span className="text-xs text-term-muted">
                  {d.marginUsed != null ? `margen ${pct(d.marginUsed)} (${d.marginSource})` : "sin valoración"} · riesgo {pct(d.riskContribPct)}
                </span>
              </summary>
              <div className="mt-2 text-xs space-y-1">
                {d.explain.motivos.map((m, i) => <div key={i}>• {m}</div>)}
                {d.explain.riesgos.length ? <div className="text-amber-300/80">Riesgos: {d.explain.riesgos.join("; ")}</div> : null}
                <div className="text-term-muted">Datos/modelos: {d.explain.datosModelos.join("; ")}</div>
                <div className="text-term-muted">Cambiaría si: {d.explain.condicionesCambio.join("; ")}</div>
              </div>
            </details>
          ))}
        </div>
      </Panel>

      <Panel title="Asignación de capital nuevo">
        <div className="flex flex-wrap gap-3 items-center mb-3 text-xs">
          <label>Aporte USD <input type="number" value={contribution} onChange={(e) => setContribution(Math.max(0, Number(e.target.value) || 0))}
            className="w-24 bg-term-panel2 border border-term-border rounded px-2 py-1" /></label>
          <label>Efectivo actual USD <input type="number" value={cash} onChange={(e) => setCash(Math.max(0, Number(e.target.value) || 0))}
            className="w-24 bg-term-panel2 border border-term-border rounded px-2 py-1" /></label>
          <span className="text-term-muted">Elegida: <strong>{r.allocation.chosen}</strong></span>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {r.allocation.options.map((o) => (
            <div key={o.id} className={`rounded border p-3 ${o.preferred ? "border-term-accent" : "border-term-border/50"}`}>
              <div className="text-sm font-medium">{o.label}{o.preferred ? " ✓" : ""}</div>
              <div className="text-xs text-term-muted mt-1">vol {pct(o.volAfter)} · HHI sector {num(o.hhiSectorAfter, 3)} · efectivo {money(o.cashKept, "USD")}</div>
              <div className="mt-2 text-xs space-y-1">
                {o.items.length ? o.items.map((it) => (
                  <div key={it.ticker}>{it.action} {it.ticker} {money(it.amount, "USD")} → peso {pct(it.newWeight)} <span className="text-term-muted">({it.reason})</span></div>
                )) : <div className="text-term-muted">Sin despliegue (todo en efectivo).</div>}
              </div>
              {o.preferred ? <div className="text-[11px] text-term-accent mt-2">{o.why}</div> : null}
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Control y explicabilidad">
        <ul className="text-xs text-term-muted list-disc pl-4 space-y-1">
          {r.guardrails.map((g, i) => <li key={i}>{g}</li>)}
          <li>Datos/modelos usados: {r.dataUsed.join("; ")}.</li>
          <li>Comparación: Advisor 2.2 sigue disponible en la pestaña «Investment Advisor» como referencia.</li>
        </ul>
      </Panel>
    </div>
  );
}
