// P3.0 Historial — consume los registros INMUTABLES (decision_record) y los evalúa con el motor real
// (evaluateDecision), SIN look-ahead y SIN recalcular valoraciones. Muestra horizontes 1/3/6/12 m,
// distingue pendiente de evaluado, y permite revisar cada decisión sin modificar sus datos. No inventa
// rendimientos ni registros: si faltan precios, el horizonte queda "sin datos"; si no hay decisiones,
// estado vacío adecuado.
import { useEffect, useState } from "react";
import { getDecisionRecords, getPriceHistory } from "../data";
import { evaluateDecision, type DecisionEvaluation, type PriceMap } from "../core/decision-eval";
import type { DecisionRecord } from "../core/decision-record";
import { num, pct } from "../format";

const HZ = [1, 3, 6, 12];

export function Historial() {
  const [recs, setRecs] = useState<DecisionRecord[] | null>(null);
  const [evals, setEvals] = useState<Record<string, DecisionEvaluation>>({});
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const records = await getDecisionRecords();
        // precios reales de los tickers involucrados (legs + benchmark + descartados) para evaluar sin inventar
        const tickers = new Set<string>();
        for (const r of records) {
          tickers.add(r.benchmark);
          r.recommendations.forEach((l) => tickers.add(l.ticker));
          r.discardedCandidates.forEach((d) => tickers.add(d.ticker));
        }
        const arr = [...tickers];
        const hist = await Promise.all(arr.map((t) => getPriceHistory(t).catch(() => [])));
        const prices: PriceMap = {};
        arr.forEach((t, i) => { prices[t] = hist[i].map((b: any) => ({ as_of: b.as_of, close: Number(b.close) })); });
        const ev: Record<string, DecisionEvaluation> = {};
        for (const r of records) ev[r.decisionId] = evaluateDecision(r, prices);
        if (!cancelled) { setRecs(records); setEvals(ev); }
      } catch (e) { if (!cancelled) setErr(String(e)); }
    })();
    return () => { cancelled = true; };
  }, []);

  if (err) return <div className="state err">No se pudieron cargar las decisiones: {err}</div>;
  if (!recs) return <div className="state">Cargando decisiones…</div>;

  if (recs.length === 0) return (
    <div>
      <div className="s-head"><div><div className="s-kick">Decisiones registradas · inmutables</div><div className="s-title">Historial</div></div></div>
      <div className="minibox" style={{ marginTop: 16 }}>
        <div style={{ fontSize: 13 }}>Aún no hay decisiones registradas.</div>
        <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 8 }}>
          Cada vez que registres una recomendación (desde Asignar mi aporte, o el emisor formal), quedará aquí como un snapshot inmutable y se evaluará a 1/3/6/12 meses a medida que exista precio real. No se muestran resultados inventados.
        </div>
      </div>
    </div>
  );

  // orden: más reciente primero
  const sorted = [...recs].sort((a, b) => b.emittedAt.localeCompare(a.emittedAt));

  return (
    <div>
      <div className="s-head"><div><div className="s-kick">{recs.length} decisión(es) · inmutables · sin look-ahead</div><div className="s-title">Historial</div></div></div>
      <div className="hist">
        {sorted.map((r) => {
          const ev = evals[r.decisionId];
          const dep = r.recommendations.reduce((s, l) => s + l.amount, 0);
          const isOpen = open === r.decisionId;
          return (
            <div className="hrec" key={r.decisionId}>
              <div className="hh">
                <span className="id">{r.decisionId}</span>
                <span className="when">emitida {r.emittedAt.slice(0, 10)} · {r.benchmark}</span>
              </div>
              <div className="legs2">
                {r.chosen === "efectivo" || r.recommendations.length === 0
                  ? "Conservar efectivo (ninguna compra superó el umbral)"
                  : `${r.recommendations.map((l) => `${l.ticker} ${num(l.amount, 0)}`).join(" · ")} · efectivo ${num(r.cash + r.contribution - dep, 0)}`}
              </div>
              <div className="legs2" style={{ color: "var(--buy)" }}>
                Riesgo {pct(r.riskBefore.vol)} → {pct(r.riskAfter.vol)} ({r.riskAfter.deltaVol >= 0 ? "+" : ""}{(r.riskAfter.deltaVol * 100).toFixed(1)} pp) · HHI {r.riskBefore.hhiSector.toFixed(3)} → {r.riskAfter.hhiSector.toFixed(3)}
              </div>

              <div className="hz">
                {HZ.map((m) => {
                  const h = ev?.horizons.find((x) => x.months === m);
                  if (!h || !h.reached) return <div className="h pending" key={m}><div className="hl">{m} {m === 1 ? "mes" : "meses"}</div><div className="hv">pendiente</div></div>;
                  if (h.allocationReturn == null) return <div className="h pending" key={m}><div className="hl">{m} {m === 1 ? "mes" : "meses"}</div><div className="hv">sin datos</div></div>;
                  return (
                    <div className="h" key={m}>
                      <div className="hl">{m} {m === 1 ? "mes" : "meses"}</div>
                      <div className="hv" style={{ color: h.allocationReturn >= 0 ? "var(--up)" : "var(--reduce)" }}>{h.allocationReturn >= 0 ? "+" : ""}{pct(h.allocationReturn)}</div>
                    </div>
                  );
                })}
              </div>

              <button className="ficha-back" style={{ marginTop: 10, marginBottom: 0 }} onClick={() => setOpen(isOpen ? null : r.decisionId)}>
                {isOpen ? "▾ Ocultar detalle" : "▸ Revisar decisión"}
              </button>

              {isOpen && (
                <div style={{ marginTop: 10, display: "grid", gap: 10 }}>
                  <div className="minibox"><h6>Valoraciones congeladas (no se recalculan)</h6>
                    {r.valuations.length === 0 && <div style={{ fontSize: 12, color: "var(--muted)" }}>Sin candidatos accionables registrados.</div>}
                    {r.valuations.map((v) => (
                      <div className="kv" key={v.ticker}><span>{v.ticker}</span><b>{v.margin != null ? (v.margin >= 0 ? "+" : "") + pct(v.margin, 0) : "n/d"} · {v.source} · {v.tier}{v.confidence ? " · " + v.confidence : ""}</b></div>
                    ))}
                  </div>
                  {ev && (
                    <div className="minibox"><h6>Evaluación vs efectivo y benchmark</h6>
                      {ev.horizons.filter((h) => h.reached && h.allocationReturn != null).map((h) => (
                        <div className="kv" key={h.months}><span>{h.months} m</span><b>asignación {pct(h.allocationReturn as number)} · vs efectivo {h.excessVsCash != null ? pctSign(h.excessVsCash) : "n/d"} · vs {r.benchmark} {h.excessVsBenchmark != null ? pctSign(h.excessVsBenchmark) : "n/d"}</b></div>
                      ))}
                      {ev.horizons.every((h) => !h.reached || h.allocationReturn == null) && <div style={{ fontSize: 12, color: "var(--muted)" }}>Sin horizontes evaluados todavía.</div>}
                    </div>
                  )}
                  {r.alternatives.length > 0 && (
                    <div className="minibox"><h6>Alternativas consideradas</h6>
                      {r.alternatives.map((a) => (<div className="kv" key={a.id}><span>{a.label || a.id}</span><b>desplegado {num(a.deployed, 0)} · efectivo {num(a.cashKept, 0)}</b></div>))}
                    </div>
                  )}
                  <div className="note" style={{ margin: 0 }}><span className="i">◆</span><span>{r.note}</span></div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="note"><span className="i">◆</span><span>Sin look-ahead: un horizonte solo muestra rendimiento cuando su fecha objetivo ya pasó y existe precio real. Faltantes = “sin datos”, nunca inventados. Los registros son inmutables; esta vista no los modifica.</span></div>
    </div>
  );
}

const pctSign = (x: number) => (x >= 0 ? "+" : "") + pct(x);
