import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Panel } from "../components/Panel";
import { getLatestRun, getLatestScan, type ScanRow } from "../data";
import { num } from "../format";

const TAG_TONE: Record<string, string> = {
  value: "text-term-good", growth: "text-term-accent", quality: "text-term-good",
  momentum: "text-term-accent", oversold: "text-term-warn", turnaround: "text-term-warn",
  neutral: "text-term-muted",
};

function Bar({ v }: { v: number }) {
  return (
    <div className="h-1.5 w-full rounded bg-term-panel2">
      <div className="h-full rounded bg-term-accent" style={{ width: `${Math.max(0, Math.min(100, v))}%` }} />
    </div>
  );
}

export function Opportunities() {
  const [scan, setScan] = useState<ScanRow[]>([]);
  const [run, setRun] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getLatestScan(), getLatestRun()])
      .then(([s, r]) => { setScan(s); setRun(r); })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <p className="text-sm text-term-crit">{err}</p>;

  return (
    <div className="grid gap-4">
      <Panel title="Global Opportunity Scanner">
        <p className="text-sm text-term-muted">
          El scanner lo ejecuta un proceso programado (GitHub Actions) sobre un universo US
          sistemático; aquí consultas el último snapshot. Puntaje multifactor de atractivo
          <strong> relativo</strong> — no es una predicción de rendimiento.
        </p>
        {run && (
          <p className="mt-2 text-xs text-term-muted">
            Última corrida: <span className="tabnum">{run.as_of}</span> · {run.evaluated} evaluados ·
            fuente {run.using_sample_data ? "EJEMPLO" : "real (Stooq/EDGAR)"} ·
            factores usables: {(run.usable_factors ?? []).join(", ") || "—"}
          </p>
        )}
      </Panel>

      {scan.length === 0 ? (
        <Panel title="Ranking">
          <p className="text-sm text-term-muted">
            Aún no hay datos. Ejecuta el workflow «GIIC scan» en GitHub (manual o espera el cron diario).
          </p>
        </Panel>
      ) : (
        <Panel title={`Ranking · ${scan.length} instrumentos`}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-term-border text-left text-xs uppercase text-term-muted">
                  <th className="py-2">#</th><th>Ticker</th><th>Sector</th>
                  <th className="w-40">Compuesto</th><th>Value</th><th>Quality</th>
                  <th>Growth</th><th>Mom.</th><th>Etiquetas</th>
                </tr>
              </thead>
              <tbody>
                {scan.map((r) => (
                  <tr key={r.ticker} className="border-b border-term-border last:border-0">
                    <td className="py-2 tabnum text-term-muted">{r.rank}</td>
                    <td><Link to={`/research/${r.ticker}`} className="font-mono font-semibold text-term-accent hover:underline">{r.ticker}</Link></td>
                    <td className="text-term-muted">{r.sector ?? "—"}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <span className="tabnum w-9">{num(r.composite, 0)}</span>
                        <Bar v={r.composite} />
                      </div>
                    </td>
                    <td className="tabnum">{num(r.factor_value, 0)}</td>
                    <td className="tabnum">{num(r.factor_quality, 0)}</td>
                    <td className="tabnum">{num(r.factor_growth, 0)}</td>
                    <td className="tabnum">{num(r.factor_momentum, 0)}</td>
                    <td className="space-x-1">
                      {(r.tags ?? []).map((t) => (
                        <span key={t} className={`text-xs ${TAG_TONE[t] ?? "text-term-muted"}`}>{t}</span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}
