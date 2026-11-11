// P2.6 — Historial de decisiones y resultados (EXPERIMENTAL, flag VITE_FF_DECISIONS). Solo lectura:
// lista los registros INMUTABLES de recomendaciones y, cuando hay horizonte suficiente, evalúa sin
// look-ahead contra efectivo y benchmark. No ejecuta operaciones; todo es SIMULADO.
import { useEffect, useState } from "react";
import { Panel } from "../components/Panel";
import { getDecisionRecords, getPriceHistory } from "../data";
import type { DecisionRecord } from "../core/decision-record";
import { evaluateDecision, type PriceMap, type DecisionEvaluation } from "../core/decision-eval";
import { money, pct } from "../format";

export function DecisionHistory() {
  const [recs, setRecs] = useState<DecisionRecord[] | null>(null);
  const [evals, setEvals] = useState<Record<string, DecisionEvaluation>>({});
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const rs = await getDecisionRecords();
      setRecs(rs);
      // evalúa cada decisión con el historial de los tickers involucrados (+ benchmark)
      const out: Record<string, DecisionEvaluation> = {};
      for (const r of rs) {
        const tickers = [...new Set([r.benchmark, ...r.recommendations.map((l) => l.ticker), ...r.discardedCandidates.map((d) => d.ticker)])];
        const prices: PriceMap = {};
        await Promise.all(tickers.map(async (t) => {
          try { prices[t] = (await getPriceHistory(t)).map((b) => ({ as_of: b.as_of, close: Number(b.close) })); }
          catch { prices[t] = []; }
        }));
        out[r.decisionId] = evaluateDecision(r, prices);
      }
      setEvals(out);
    })().catch((e) => setErr(String(e))).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8 text-term-muted">Cargando historial de decisiones…</div>;
  if (err) return <div className="p-8 text-rose-400">Error: {err}</div>;
  if (!recs || !recs.length) return <div className="p-8 text-term-muted">Sin decisiones registradas. Emite una con el job de registro (rol de servicio).</div>;

  return (
    <div className="p-4 md:p-6 space-y-3">
      <div className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-200">
        <strong>Historial de decisiones — experimental</strong> (P2.6). Registros INMUTABLES de
        recomendaciones <strong>SIMULADAS</strong> (no operaciones ejecutadas). Evaluación posterior sin
        look-ahead; efectivo = 0%; datos faltantes = no disponible.
      </div>

      {recs.map((r) => {
        const ev = evals[r.decisionId];
        return (
          <Panel key={r.decisionId} title={`${r.decisionId} · ${new Date(r.emittedAt).toISOString().slice(0, 16).replace("T", " ")} · ${r.chosen} · aporte ${money(r.contribution, "USD")}`}>
            <div className="text-xs space-y-2">
              <div className="text-term-muted">
                Universo {r.universe.evaluated}/{r.universe.total} · benchmark {r.benchmark} · algo {r.algoVersion}
                {" · riesgo "}{pct(r.riskBefore.vol)} → {pct(r.riskAfter.vol)} (Δ {pct(r.riskAfter.deltaVol)})
              </div>
              <div>
                <span className="text-term-muted">Recomendación: </span>
                {r.recommendations.length ? r.recommendations.map((l) => `${l.ticker} ${money(l.amount, "USD")}`).join(" · ") : "mantener efectivo"}
              </div>
              {r.recommendations.length ? (
                <div className="text-term-muted">
                  Valoración: {r.recommendations.map((l) => `${l.ticker} ${l.margin != null ? pct(l.margin) : "n/d"}/${l.confidence ?? "n/d"}`).join(" · ")}
                </div>
              ) : null}
              {r.discardedCandidates.length ? <div className="text-term-muted">Descartados: {r.discardedCandidates.map((d) => d.ticker).join(", ")}</div> : null}

              {ev ? (
                <div className="mt-1 overflow-x-auto">
                  <table className="w-full text-[11px]">
                    <thead className="text-term-muted"><tr>
                      <th className="text-left">Horizonte</th><th>Estado</th><th>Asignación</th><th>Efectivo</th><th>{r.benchmark}</th><th>vs efectivo</th><th>vs bench</th><th>Vol real</th><th>Drawdown</th>
                    </tr></thead>
                    <tbody>
                      {ev.horizons.map((h) => (
                        <tr key={h.months} className="text-center">
                          <td className="text-left">{h.months}m <span className="text-term-muted">({h.targetDate})</span></td>
                          <td>{h.reached ? "✓" : "pendiente"}</td>
                          <td>{h.allocationReturn != null ? pct(h.allocationReturn) : "—"}</td>
                          <td>{h.reached ? pct(h.cashReturn) : "—"}</td>
                          <td>{h.benchmarkReturn != null ? pct(h.benchmarkReturn) : "—"}</td>
                          <td className={h.excessVsCash != null ? (h.excessVsCash >= 0 ? "text-term-accent" : "text-term-crit") : ""}>{h.excessVsCash != null ? pct(h.excessVsCash) : "—"}</td>
                          <td className={h.excessVsBenchmark != null ? (h.excessVsBenchmark >= 0 ? "text-term-accent" : "text-term-crit") : ""}>{h.excessVsBenchmark != null ? pct(h.excessVsBenchmark) : "—"}</td>
                          <td>{h.realizedVol != null ? pct(h.realizedVol) : "—"}</td>
                          <td>{h.maxDrawdown != null ? pct(h.maxDrawdown) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {ev.horizons.some((h) => h.reached && h.missing.length) ? (
                    <div className="text-[11px] text-amber-300/80 mt-1">Datos faltantes: {[...new Set(ev.horizons.flatMap((h) => h.missing))].filter((m) => !/no alcanzado/.test(m)).join("; ")}</div>
                  ) : null}
                </div>
              ) : null}
            </div>
          </Panel>
        );
      })}
    </div>
  );
}
