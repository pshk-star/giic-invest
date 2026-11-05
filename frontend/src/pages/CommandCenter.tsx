import { useEffect, useState } from "react";
import { Panel, Stat } from "../components/Panel";
import {
  concentrationReport, lookThrough, valuation,
  type Position, type Valuation,
} from "../core/analytics";
import { getEtfHoldings, getFxRates, getLatestRun, getLatestScan, getPositions, getPrices, type ScanRow } from "../data";
import { money, num, pct } from "../format";

// Dashboard — ¿qué hago hoy con mi dinero? (Fase $0: estado, concentración, calidad
// de la información y top de oportunidades del scanner. Sin recomendaciones
// probabilísticas sin validación.)
export function CommandCenter() {
  const [val, setVal] = useState<Valuation | null>(null);
  const [lt, setLt] = useState<ReturnType<typeof lookThrough> | null>(null);
  const [scan, setScan] = useState<ScanRow[]>([]);
  const [run, setRun] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const pos = (await getPositions()) as (Position & { id: string })[];
      if (pos.length) {
        const prices = await getPrices(pos.map((p) => p.ticker));
        const fx = await getFxRates("USD");
        const etfs = pos.filter((p) => p.asset_class === "etf").map((p) => p.ticker);
        const holdings = await getEtfHoldings(etfs);
        setVal(valuation(pos, prices, fx));
        setLt(lookThrough(pos, prices, holdings, fx));
      }
      setScan(await getLatestScan());
      setRun(await getLatestRun());
    })().catch((e) => setErr(String(e)));
  }, []);

  if (err) return <p className="text-sm text-term-crit">{err}</p>;

  const conc = lt ? concentrationReport(lt, 0.25) : null;

  return (
    <div className="grid gap-4">
      <Panel title="Investment Command Center">
        {val ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Valor de cartera" value={money(val.total_market_value)} />
            <Stat label="Posiciones efectivas" value={conc ? num(conc.effective_holdings, 1) : "—"} />
            <Stat label="Concentración (HHI)" value={conc ? num(conc.hhi, 3) : "—"}
              tone={conc && conc.hhi > 0.2 ? "text-term-warn" : "text-term-good"} />
            <Stat label="Exposición máxima"
              value={conc?.top_exposure ? pct(conc.top_exposure.effective_weight) : "—"}
              tone={conc?.top_exposure && conc.top_exposure.effective_weight > conc.limit ? "text-term-crit" : "text-term-fg"} />
          </div>
        ) : (
          <p className="text-sm text-term-muted">Sin cartera todavía. Agrégala en «Mi Cartera».</p>
        )}
      </Panel>

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Riesgos de concentración (look-through)">
          {!conc ? (
            <p className="text-sm text-term-muted">—</p>
          ) : conc.breaches.length === 0 ? (
            <p className="text-sm text-term-good">Ninguna exposición efectiva supera {pct(conc.limit)}.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {conc.breaches.map((b) => (
                <li key={b.ticker} className="flex items-center justify-between rounded-lg border border-term-crit/40 bg-term-crit/5 px-3 py-2 text-sm">
                  <span className="font-mono font-semibold">{b.ticker}</span>
                  <span className="text-term-crit">{pct(b.effective_weight)} (límite {pct(conc.limit)})</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Oportunidades del scanner (top)">
          {scan.length === 0 ? (
            <p className="text-sm text-term-muted">Aún no hay snapshot del scanner. Corre el job (ver Oportunidades).</p>
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
      </div>

      <Panel title="Calidad de la información">
        {run ? (
          <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div><div className="text-xs uppercase text-term-muted">Última actualización</div><div className="tabnum">{run.as_of}</div></div>
            <div><div className="text-xs uppercase text-term-muted">Instrumentos evaluados</div><div className="tabnum">{run.evaluated}</div></div>
            <div><div className="text-xs uppercase text-term-muted">Fuente</div><div>{run.using_sample_data ? "EJEMPLO" : "real (Stooq/EDGAR)"}</div></div>
            <div><div className="text-xs uppercase text-term-muted">Factores usables</div><div className="text-xs">{(run.usable_factors ?? []).join(", ")}</div></div>
          </div>
        ) : (
          <p className="text-sm text-term-muted">Sin corridas registradas aún.</p>
        )}
        {val && val.missing_prices.length > 0 && (
          <p className="mt-3 text-xs text-term-warn">Datos faltantes: {val.missing_prices.join(", ")}.</p>
        )}
      </Panel>
    </div>
  );
}
