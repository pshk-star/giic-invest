import { useEffect, useRef, useState } from "react";
import { Panel } from "../components/Panel";
import { getLatestScan, searchInstruments, type InstrumentRow, type ScanRow } from "../data";
import { StockFiche } from "./Ficha";
import { num } from "../format";

// Buscador y análisis de acciones: escribe un ticker o nombre y obtén la ficha de inversión
// (precio, gráfico, proyecciones del modelo, fundamentales, riesgos) SIN salir de la pantalla.
export function Research() {
  const [q, setQ] = useState("");
  const [sugs, setSugs] = useState<InstrumentRow[]>([]);
  const [scan, setScan] = useState<ScanRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
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

  const pick = (ticker: string) => {
    const t = ticker.toUpperCase().trim();
    if (!t) return;
    setSelected(t); setSugs([]); setQ(t);
  };

  return (
    <div className="grid gap-4">
      <Panel title="Análisis de acciones">
        <p className="text-sm text-term-muted">
          Escribe un ticker o nombre (p. ej. NVDA, INTC, ASML) y pulsa Enter, o elige de la lista.
          Obtendrás precio, gráfico, proyecciones del modelo (si hay cobertura), fundamentales y riesgos.
        </p>
        <input
          value={q}
          onChange={(e) => onSearch(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") pick(q); }}
          placeholder="Busca o escribe un ticker y pulsa Enter (NVDA, INTC, ASML…)"
          className="mt-3 w-full rounded-md border border-term-border bg-term-panel2 px-3 py-2 text-sm text-term-fg"
          autoComplete="off"
        />
        {sugs.length > 0 && (
          <ul className="mt-2 grid gap-1">
            {sugs.map((s) => (
              <li key={s.ticker}>
                <button
                  onClick={() => pick(s.ticker)}
                  className="flex w-full items-center justify-between gap-2 rounded-md border border-term-border bg-term-panel2 px-3 py-2 text-left text-sm hover:border-term-accent">
                  <span className="font-mono font-semibold">{s.ticker}</span>
                  <span className="flex-1 truncate text-term-muted">{s.name ?? "—"}</span>
                  <span className="text-xs text-term-accent">{s.asset_class ?? ""}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {selected && (
        <div className="rounded-xl border border-term-border p-0.5">
          <StockFiche ticker={selected} embedded />
        </div>
      )}

      {!selected && scan.length > 0 && (
        <Panel title={`Ranking del scanner · ${scan.length} instrumentos (clic para analizar)`}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="border-b border-term-border text-left text-xs uppercase text-term-muted">
                  <th className="py-2">#</th><th>Ticker</th><th>Sector</th>
                  <th className="text-right">Score</th>
                </tr>
              </thead>
              <tbody>
                {scan.slice(0, 20).map((r) => (
                  <tr key={r.ticker}
                      className="cursor-pointer border-b border-term-border last:border-0 hover:bg-term-panel2"
                      onClick={() => pick(r.ticker)}>
                    <td className="py-1.5 tabnum text-term-muted">{r.rank}</td>
                    <td className="font-mono font-semibold text-term-accent">{r.ticker}</td>
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
