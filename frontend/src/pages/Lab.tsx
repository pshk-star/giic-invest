import { useEffect, useMemo, useState } from "react";
import { Panel, Stat } from "../components/Panel";
import { getPredictions, getPredictionOutcomes, type PredictionRow, type OutcomeRow } from "../data";
import { num } from "../format";

// Laboratorio de modelos — ventana al backend cuantitativo: muestra las predicciones
// prospectivas REALES almacenadas (modelos, fechas, horizontes, estado de evaluación).
// EXPERIMENTAL / NO VALIDADO: no es recomendación de inversión.

interface Group {
  key: string;
  model: string;
  version: string;
  horizon: number;
  as_of: string;
  evaluate_on: string;
  status: string;
  rows: PredictionRow[];
}

const todayISO = () => new Date().toISOString().slice(0, 10);

export function Lab() {
  const [preds, setPreds] = useState<PredictionRow[]>([]);
  const [outcomes, setOutcomes] = useState<OutcomeRow[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [p, o] = await Promise.all([getPredictions(), getPredictionOutcomes()]);
      setPreds(p); setOutcomes(o);
    })().catch((e) => setErr(String(e))).finally(() => setLoading(false));
  }, []);

  const groups = useMemo<Group[]>(() => {
    const by = new Map<string, PredictionRow[]>();
    for (const r of preds) {
      const k = `${r.model_name}|${r.model_version}|${r.horizon_sessions}|${r.as_of}`;
      (by.get(k) ?? by.set(k, []).get(k)!).push(r);
    }
    const today = todayISO();
    const gs: Group[] = [];
    for (const [k, rows] of by) {
      const r0 = rows[0];
      const matured = r0.evaluate_on <= today;
      gs.push({
        key: k, model: r0.model_name, version: r0.model_version, horizon: r0.horizon_sessions,
        as_of: r0.as_of, evaluate_on: r0.evaluate_on,
        status: matured ? "madura" : "pendiente", rows,
      });
    }
    gs.sort((a, b) => a.model.localeCompare(b.model) || a.horizon - b.horizon);
    return gs;
  }, [preds]);

  const asOf = preds.length ? preds[0].as_of : null;
  const emittedAt = preds.find((p) => p.emitted_at)?.emitted_at ?? null;
  const models = new Set(preds.map((p) => `${p.model_name} ${p.model_version}`));
  const status = preds[0]?.data_ref?.status ?? "EXPERIMENTAL_NO_VALIDADO";

  const selGroup = groups.find((g) => g.key === (sel ?? groups[0]?.key));
  const topRows = useMemo(() => {
    if (!selGroup) return [];
    return [...selGroup.rows]
      .sort((a, b) => (b.prediction?.pct_rank ?? 0) - (a.prediction?.pct_rank ?? 0))
      .slice(0, 10);
  }, [selGroup]);

  if (loading) return <div className="grid gap-3">{[0, 1, 2].map((i) => (
    <div key={i} className="h-24 animate-pulse rounded-xl bg-term-panel2" />))}</div>;
  if (err) return <p className="text-sm text-term-crit">Error al leer el backend: {err}</p>;
  if (!preds.length) return <p className="text-sm text-term-muted">No hay predicciones almacenadas todavía.</p>;

  return (
    <div className="grid gap-4">
      <div className="rounded-lg border border-term-warn/40 bg-term-warn/10 px-3 py-2 text-xs text-term-warn">
        <strong>EXPERIMENTAL · NO VALIDADO.</strong> Predicciones prospectivas de investigación; no constituyen
        recomendación de inversión. Benchmark de habilidad = equiponderado del universo. Modelos sin ventaja
        estadística demostrada.
      </div>

      <Panel title="Emisión prospectiva (backend real)">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Modelos" value={String(models.size)} />
          <Stat label="Predicciones" value={String(preds.length)} />
          <Stat label="Fecha de emisión" value={asOf ?? "—"} />
          <Stat label="Emitidas (UTC)" value={emittedAt ? emittedAt.slice(0, 16).replace("T", " ") : "—"} />
        </div>
        <p className="mt-2 text-xs text-term-muted">Estado: {status} · origin=production · registro inmutable.</p>
      </Panel>

      <Panel title="Modelos, horizontes y estado de evaluación">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-term-muted">
                <th className="py-1.5">Modelo</th><th>Versión</th>
                <th className="text-right">Horizonte (ses.)</th>
                <th>Emisión</th><th>Evalúa en</th>
                <th className="text-right">Activos</th><th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.key}
                    className={`cursor-pointer border-b border-term-border last:border-0 hover:bg-term-panel2 ${
                      selGroup?.key === g.key ? "bg-term-panel2" : ""}`}
                    onClick={() => setSel(g.key)}>
                  <td className="py-2 font-mono">{g.model}</td>
                  <td className="text-term-muted">{g.version}</td>
                  <td className="text-right tabnum">{g.horizon}</td>
                  <td className="tabnum">{g.as_of}</td>
                  <td className="tabnum">{g.evaluate_on}</td>
                  <td className="text-right tabnum">{g.rows.length}</td>
                  <td>
                    <span className={`rounded px-1.5 py-0.5 text-xs ${
                      g.status === "madura" ? "bg-term-good/15 text-term-good" : "bg-term-panel2 text-term-muted"}`}>
                      {g.status === "madura" ? "madura" : `pendiente · vence ${g.evaluate_on}`}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-term-muted">
          Evaluación registrada: {outcomes.length} resultado(s). Una predicción se evalúa cuando su fecha
          «evalúa en» (en sesiones NYSE) ya pasó.
        </p>
      </Panel>

      {selGroup && (
        <Panel title={`Sección transversal — ${selGroup.model} ${selGroup.version} @${selGroup.horizon}s (top 10 por percentil)`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-term-muted">
                  <th className="py-1.5">#</th><th>Activo</th>
                  <th className="text-right">Retorno rel. previsto</th>
                  <th className="text-right">Percentil</th>
                </tr>
              </thead>
              <tbody>
                {topRows.map((r, i) => (
                  <tr key={r.ticker} className="border-b border-term-border last:border-0">
                    <td className="py-1.5 tabnum text-term-muted">{i + 1}</td>
                    <td className="font-mono font-semibold">{r.ticker}</td>
                    <td className="text-right tabnum">{r.prediction?.rel_return != null ? `${(r.prediction.rel_return * 100).toFixed(2)}%` : "—"}</td>
                    <td className="text-right tabnum">{r.prediction?.pct_rank != null ? num(r.prediction.pct_rank * 100, 0) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-term-faint">
            Ranking transversal del modelo (mayor percentil = mejor previsto, relativo al universo). Observación
            del modelo, NO recomendación.
          </p>
        </Panel>
      )}
    </div>
  );
}
