import { useEffect, useMemo, useState } from "react";
import { Panel } from "../components/Panel";
import {
  getInstruments, getLatestRun, getLatestScan, getPrices, getSettings, getTransactions,
  saveSettings, type ScanRow,
} from "../data";
import { derivePositions, portfolioTotals } from "../core/portfolio-tx";
import {
  buildAdvice, type AdvisorReport, type Holding, type Recommendation, type ScanInfo,
} from "../core/advisor";
import { money, num, pct } from "../format";

export function Advisor() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [scan, setScan] = useState<ScanInfo[]>([]);
  const [scanAsOf, setScanAsOf] = useState<string | undefined>();
  const [cash, setCash] = useState(3000);
  const [maxAsset, setMaxAsset] = useState(0.25);
  const [maxSector, setMaxSector] = useState(0.40);
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const txns = await getTransactions();
      const tickers = Array.from(new Set(txns.map((t) => t.ticker.toUpperCase())));
      const [prices, instruments, rows, run, settings] = await Promise.all([
        getPrices(tickers), getInstruments(tickers), getLatestScan(), getLatestRun(), getSettings(),
      ]);
      const pos = derivePositions(txns, prices, instruments);
      const totals = portfolioTotals(pos);
      const hs: Holding[] = pos
        .filter((p) => p.qty > 1e-9)
        .map((p) => ({
          ticker: p.ticker, name: p.name,
          sector: instruments[p.ticker]?.sector ?? null,
          assetClass: instruments[p.ticker]?.asset_class ?? p.asset_class ?? null,
          marketValue: p.marketValue,
          weight: totals.weights[p.ticker] ?? 0,
          priceAsOf: p.priceAsOf,
        }));
      setHoldings(hs);
      setScan(rows.map(scanRowToInfo));
      setScanAsOf(run?.as_of);
      if (settings) {
        setCash(settings.capital_available || 3000);
        setMaxAsset(settings.max_weight_per_asset || 0.25);
        setMaxSector(settings.max_weight_per_sector || 0.40);
      }
      setLoaded(true);
    })().catch((e) => setErr(String(e)));
  }, []);

  const report: AdvisorReport = useMemo(
    () => buildAdvice(holdings, scan, cash, { maxWeightAsset: maxAsset, maxWeightSector: maxSector }, scanAsOf),
    [holdings, scan, cash, maxAsset, maxSector, scanAsOf]
  );

  const persist = async () => {
    try {
      await saveSettings({
        capital_available: cash, max_weight_per_asset: maxAsset, max_weight_per_sector: maxSector,
      });
      setSavedMsg("Guardado."); setTimeout(() => setSavedMsg(null), 2000);
    } catch (e) { setErr(String(e)); }
  };

  if (err) return <p className="text-sm text-term-crit">{err}</p>;
  if (!loaded) return <p className="text-sm text-term-muted">Cargando…</p>;

  const noData = holdings.length === 0;

  return (
    <div className="grid gap-4">
      <Panel title="Investment Advisor"
        right={savedMsg ? <span className="text-xs text-term-good">{savedMsg}</span> : undefined}>
        <p className="text-sm text-term-muted">
          Motor determinístico sobre tus datos reales (posiciones, precios, scanner). Reglas
          transparentes y escenarios — <strong>no</strong> pronostica retornos ni probabilidades.
        </p>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <label className="text-xs text-term-muted">Capital a evaluar (USD)
            <input type="number" value={cash} min={0} step={500}
              onChange={(e) => setCash(Number(e.target.value) || 0)}
              className="mt-1 w-full rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm text-term-fg" />
          </label>
          <label className="text-xs text-term-muted">Máx. por activo
            <input type="number" value={Math.round(maxAsset * 100)} min={1} max={100} step={1}
              onChange={(e) => setMaxAsset((Number(e.target.value) || 25) / 100)}
              className="mt-1 w-full rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm text-term-fg" />
            <span className="text-term-faint">%</span>
          </label>
          <label className="text-xs text-term-muted">Máx. por sector
            <input type="number" value={Math.round(maxSector * 100)} min={1} max={100} step={1}
              onChange={(e) => setMaxSector((Number(e.target.value) || 40) / 100)}
              className="mt-1 w-full rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm text-term-fg" />
            <span className="text-term-faint">%</span>
          </label>
          <button onClick={persist}
            className="mt-4 h-9 self-start rounded-md border border-term-border bg-term-panel2 px-3 text-sm text-term-fg hover:border-term-accent">
            Guardar límites
          </button>
        </div>
      </Panel>

      {noData && (
        <Panel title="Primero carga tu cartera">
          <p className="text-sm text-term-muted">
            Registra tus operaciones en «Mi Cartera»: el Advisor analiza tus posiciones reales,
            no un ejemplo.
          </p>
        </Panel>
      )}

      {!noData && (
        <>
          {/* Asignación de capital */}
          <Panel title={`¿Dónde evaluar ${money(cash)}?`}>
            <p className="mb-2 text-sm text-term-muted">{report.allocation.note}</p>
            <p className="mb-1 text-xs text-term-faint">{report.allocation.basisNote}</p>
            <p className="mb-3 text-xs text-term-faint">{report.allocation.method}</p>
            {report.allocation.items.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[620px] text-sm">
                  <thead>
                    <tr className="border-b border-term-border text-left text-xs uppercase text-term-muted">
                      <th className="py-2">Ticker</th><th>Acción</th>
                      <th className="text-right">Monto</th><th className="text-right">Peso resultante</th>
                      <th className="text-right">Score</th><th>Por qué</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.allocation.items.map((it) => (
                      <tr key={it.ticker} className="border-b border-term-border last:border-0 align-top">
                        <td className="py-2 font-mono font-semibold">{it.ticker}</td>
                        <td>{it.kind === "add_existing" ? "Aumentar" : "Nueva"}</td>
                        <td className="text-right tabnum text-term-good">{money(it.amount)}</td>
                        <td className="text-right tabnum">{pct(it.newWeight)}</td>
                        <td className="text-right tabnum">{num(it.composite, 0)}</td>
                        <td className="max-w-[260px] text-xs text-term-muted">{it.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-4 text-xs text-term-muted">
              <span>Invertir: <b className="text-term-fg tabnum">{money(report.allocation.invested)}</b></span>
              <span>Liquidez restante: <b className="text-term-fg tabnum">{money(report.allocation.cashLeftover)}</b></span>
              <span>Concentración (HHI): {num(report.allocation.before.hhi, 3)} → <b className="text-term-fg">{num(report.allocation.after.hhi, 3)}</b></span>
              <span>Exposición máx.: {pct(report.allocation.before.topWeight)} → <b className="text-term-fg">{pct(report.allocation.after.topWeight)}</b></span>
            </div>
          </Panel>

          {/* Cumplimiento residual */}
          <Panel title="¿Esta sugerencia deja tu cartera dentro de tus límites?">
            {report.compliance.ok ? (
              <p className="text-sm text-term-good">
                Sí: tras la sugerencia ningún activo ni sector superaría tus límites.
              </p>
            ) : (
              <div className="grid gap-1">
                <p className="text-sm text-term-warn">
                  No del todo — estos incumplimientos <b>persisten</b> y aportar capital nuevo no los resuelve:
                </p>
                <ul className="flex flex-col gap-0.5 text-xs text-term-muted">
                  {report.compliance.remaining.map((r, i) => <li key={i}>• {r}</li>)}
                </ul>
              </div>
            )}
          </Panel>

          {/* Alternativas */}
          <Panel title="Alternativas a considerar">
            <ul className="flex flex-col gap-2 text-sm text-term-muted">
              {report.alternatives.map((a, i) => <li key={i}>• {a}</li>)}
            </ul>
          </Panel>

          {/* Timing */}
          <Panel title="¿Comprar, esperar o por tramos?">
            <ul className="flex flex-col gap-2 text-sm text-term-muted">
              {report.timing.map((t, i) => <li key={i}>• {t}</li>)}
            </ul>
          </Panel>

          {/* Diagnóstico de cartera */}
          <Panel title="Qué corregir en tu cartera">
            {report.diagnostics.length === 0 ? (
              <p className="text-sm text-term-good">Sin alertas de concentración ni posiciones débiles según tus límites.</p>
            ) : (
              <div className="grid gap-2">{report.diagnostics.map((d, i) => <RecoCard key={i} r={d} />)}</div>
            )}
          </Panel>

          {/* Ranking de oportunidades (separado de la asignación) */}
          <Panel title="Ranking de oportunidades (fuera de tu cartera)">
            <p className="mb-2 text-xs text-term-faint">
              Orden por atractivo relativo del scanner. Es un <b>ranking</b>, no una instrucción de
              compra ni un reparto de capital — eso se decide arriba, por diversificación.
            </p>
            {report.ideas.length === 0 ? (
              <p className="text-sm text-term-muted">Ninguna no-tenencia supera tu umbral de score hoy.</p>
            ) : (
              <div className="grid gap-2">{report.ideas.map((d, i) => <RecoCard key={i} r={d} />)}</div>
            )}
          </Panel>

          {report.dataGaps.length > 0 && (
            <Panel title="Datos faltantes">
              <ul className="flex flex-col gap-1 text-xs text-term-warn">
                {report.dataGaps.map((d, i) => <li key={i}>• {d}</li>)}
              </ul>
            </Panel>
          )}

          <Panel title="Datos utilizados (fecha y procedencia)">
            <ul className="flex flex-col gap-1 text-xs text-term-muted">
              {report.dataUsed.map((d, i) => <li key={i}>• {d}</li>)}
            </ul>
          </Panel>
        </>
      )}
    </div>
  );
}

function RecoCard({ r }: { r: Recommendation }) {
  const [open, setOpen] = useState(false);
  const tone = r.kind === "reduce" || r.kind === "trim_sector" || r.kind === "hold_weak"
    ? "text-term-warn" : "text-term-good";
  return (
    <div className="rounded-lg border border-term-border bg-term-panel2 p-3">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between gap-2 text-left">
        <span className="text-sm"><span className={`font-mono font-semibold ${tone}`}>{r.ticker}</span> — {r.conclusion}</span>
        <span className="text-xs text-term-faint">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="mt-2 grid gap-2 text-xs">
          <Block title="Justificación" items={r.justification} tone="text-term-fg" />
          <Block title="Riesgos" items={r.risks} tone="text-term-muted" />
          <Block title="Qué cambiaría la recomendación" items={r.conditions} tone="text-term-muted" />
        </div>
      )}
    </div>
  );
}

function Block({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-term-faint">{title}</div>
      <ul className={`mt-0.5 flex flex-col gap-0.5 ${tone}`}>
        {items.map((x, i) => <li key={i}>• {x}</li>)}
      </ul>
    </div>
  );
}

function scanRowToInfo(r: ScanRow): ScanInfo {
  return {
    ticker: r.ticker, name: null, sector: r.sector,
    composite: r.composite,
    factors: {
      value: r.factor_value ?? 0, quality: r.factor_quality ?? 0, growth: r.factor_growth ?? 0,
      momentum: r.factor_momentum ?? 0, low_risk: r.factor_low_risk ?? 0,
    },
    tags: r.tags ?? [],
  };
}
