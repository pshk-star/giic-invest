import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Panel } from "../components/Panel";
import { getLatestScan, searchInstruments, type InstrumentRow, type ScanRow } from "../data";
import { num } from "../format";

// Índice de Research: busca cualquier instrumento del catálogo y abre su ficha; además
// lista el ranking del scanner como accesos directos clicables.
export function Research() {
  const [q, setQ] = useState("");
  const [sugs, setSugs] = useState<InstrumentRow[]>([]);
  const [scan, setScan] = useState<ScanRow[]>([]);
  const timer = useRef<number | null>(null);

  useEffect(() => { getLatestScan().then(setScan).catch(() => setScan([])); }, []);

  const onSearch = (v: string) => {
    setQ(v);
    if (timer.current) window.clearTimeout(timer.current);
    if (!v.trim()) { setSugs([]); return; }
    timer.current = window.setTimeout(async () => {
      try { setSugs(await searchInstruments(v)); } catch { setSugs([]); }
    }, 200);
  };

  return (
    <div className="grid gap-4">
      <Panel title="Research de empresas">
        <p className="text-sm text-term-muted">
          Ficha por instrumento con fundamentales reales, valoración relativa por comparables,
          explicación de los factores del scanner y riesgos. Busca cualquier ticker del catálogo.
        </p>
        <input
          value={q} onChange={(e) => onSearch(e.target.value)}
          placeholder="Busca un ticker o nombre (ej. NVDA, ASML, Taiwan Semi)…"
          className="mt-3 w-full rounded-md border border-term-border bg-term-panel2 px-3 py-2 text-sm text-term-fg"
          autoComplete="off"
        />
        {sugs.length > 0 && (
          <ul className="mt-2 grid gap-1">
            {sugs.map((s) => (
              <li key={s.ticker}>
                <Link to={`/research/${s.ticker}`}
                  className="flex items-center justify-between gap-2 rounded-md border border-term-border bg-term-panel2 px-3 py-2 text-sm hover:border-term-accent">
                  <span className="font-mono font-semibold">{s.ticker}</span>
                  <span className="flex-1 truncate text-term-muted">{s.name ?? "—"}</span>
                  <span className="text-xs text-term-accent">{s.asset_class ?? ""}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {scan.length > 0 && (
        <Panel title={`Ranking del scanner · ${scan.length} instrumentos (clic para ver ficha)`}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="border-b border-term-border text-left text-xs uppercase text-term-muted">
                  <th className="py-2">#</th><th>Ticker</th><th>Sector</th><th className="text-right">Score</th>
                </tr>
              </thead>
              <tbody>
                {scan.slice(0, 30).map((r) => (
                  <tr key={r.ticker} className="border-b border-term-border last:border-0">
                    <td className="py-2 tabnum text-term-muted">{r.rank}</td>
                    <td><Link to={`/research/${r.ticker}`} className="font-mono font-semibold text-term-accent hover:underline">{r.ticker}</Link></td>
                    <td className="text-term-muted">{r.sector ?? "—"}</td>
                    <td className="text-right tabnum">{num(r.composite, 0)}</td>
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
