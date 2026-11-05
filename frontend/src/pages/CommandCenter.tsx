import { useEffect, useState } from "react";
import { Panel, Stat } from "../components/Panel";
import {
  getInstruments, getLatestRun, getLatestScan, getPrices, getTransactions, type ScanRow,
} from "../data";
import {
  derivePositions, portfolioTotals, type DerivedPosition, type PortfolioTotals,
} from "../core/portfolio-tx";
import { money, num, pct } from "../format";

// Dashboard — entender mi situación en menos de un minuto: patrimonio, mejores/peores
// posiciones, oportunidades del scanner y calidad de la información.
export function CommandCenter() {
  const [positions, setPositions] = useState<DerivedPosition[]>([]);
  const [totals, setTotals] = useState<PortfolioTotals | null>(null);
  const [scan, setScan] = useState<ScanRow[]>([]);
  const [run, setRun] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const txns = await getTransactions();
      if (txns.length) {
        const tickers = Array.from(new Set(txns.map((t) => t.ticker.toUpperCase())));
        const [prices, instruments] = await Promise.all([getPrices(tickers), getInstruments(tickers)]);
        const pos = derivePositions(txns, prices, instruments);
        setPositions(pos);
        setTotals(portfolioTotals(pos));
      }
      setScan(await getLatestScan());
      setRun(await getLatestRun());
    })().catch((e) => setErr(String(e)));
  }, []);

  if (err) return <p className="text-sm text-term-crit">{err}</p>;

  const open = positions.filter((p) => p.qty > 1e-9 && p.unrealizedPct !== null);
  const sorted = [...open].sort((a, b) => (b.unrealizedPct ?? 0) - (a.unrealizedPct ?? 0));
  const best = sorted.slice(0, 3);
  const worst = sorted.slice(-3).reverse();

  return (
    <div className="grid gap-4">
      <Panel title="Mi patrimonio invertido">
        {totals && positions.length ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Valor de mercado" value={money(totals.marketValue)} />
            <Stat label="Costo (remanente)" value={money(totals.costBasis)} />
            <Stat label="P&L no realizado"
              value={totals.unrealizedPct !== null ? pct(totals.unrealizedPct) : "—"}
              tone={totals.unrealized >= 0 ? "text-term-good" : "text-term-crit"} />
            <Stat label="Realizado + div." value={money(totals.realized + totals.dividends)}
              tone={totals.realized + totals.dividends >= 0 ? "text-term-good" : "text-term-crit"} />
          </div>
        ) : (
          <p className="text-sm text-term-muted">Sin operaciones todavía. Regístralas en «Mi Cartera».</p>
        )}
      </Panel>

      {open.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          <Panel title="Mejores posiciones">
            <PosList rows={best} />
          </Panel>
          <Panel title="Peores posiciones">
            <PosList rows={worst} />
          </Panel>
        </div>
      )}

      <Panel title="Oportunidades del scanner (top)">
        {scan.length === 0 ? (
          <p className="text-sm text-term-muted">Sin snapshot del scanner todavía.</p>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {scan.slice(0, 6).map((r) => (
                <tr key={r.ticker} className="border-b border-term-border last:border-0">
                  <td className="py-1.5 tabnum text-term-muted">{r.rank}</td>
                  <td className="font-mono">{r.ticker}</td>
                  <td className="text-term-muted">{r.sector ?? "—"}</td>
                  <td className="text-right tabnum">{num(r.composite, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Calidad de la información">
        {run ? (
          <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div><div className="text-xs uppercase text-term-muted">Última actualización</div><div className="tabnum">{run.as_of}</div></div>
            <div><div className="text-xs uppercase text-term-muted">Evaluados</div><div className="tabnum">{run.evaluated}</div></div>
            <div><div className="text-xs uppercase text-term-muted">Fuente</div><div>{run.using_sample_data ? "EJEMPLO" : "real"}</div></div>
            <div><div className="text-xs uppercase text-term-muted">Estado</div><div>{run.status}</div></div>
          </div>
        ) : (
          <p className="text-sm text-term-muted">Sin corridas registradas aún.</p>
        )}
      </Panel>
    </div>
  );
}

function PosList({ rows }: { rows: DerivedPosition[] }) {
  if (rows.length === 0) return <p className="text-sm text-term-muted">—</p>;
  return (
    <table className="w-full text-sm">
      <tbody>
        {rows.map((p) => (
          <tr key={p.ticker} className="border-b border-term-border last:border-0">
            <td className="py-1.5 font-mono font-semibold">{p.ticker}</td>
            <td className="max-w-[160px] truncate text-term-muted">{p.name ?? "—"}</td>
            <td className={`text-right tabnum ${(p.unrealizedPct ?? 0) >= 0 ? "text-term-good" : "text-term-crit"}`}>
              {p.unrealizedPct !== null ? pct(p.unrealizedPct) : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
