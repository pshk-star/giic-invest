import { useEffect, useMemo, useState } from "react";
import { Panel } from "../components/Panel";
import {
  getCorporateActions, getInstruments, getPriceHistory, getPrices, getQuotes, getTransactions,
} from "../data";
import { derivePositions } from "../core/portfolio-tx";
import { mergeValuation } from "../core/price-source";
import { forecast, type AssetHistory, type ForecastResult } from "../core/forecast";
import { money } from "../format";

const ETF_CLASSES = ["etf", "fund", "etn", "mutualfund"];

// alinea historiales a fechas comunes y calcula retornos diarios por activo
function alignReturns(hist: Record<string, { as_of: string; close: number }[]>, tickers: string[]): Record<string, number[]> {
  const maps = tickers.map((t) => new Map((hist[t] ?? []).map((b) => [b.as_of, b.close])));
  let common: string[] | null = null;
  tickers.forEach((t, i) => {
    const dates = [...maps[i].keys()];
    common = common === null ? dates : common.filter((d) => maps[i].has(d));
  });
  const dates = (common ?? []).sort().slice(-520); // ~2 años
  const out: Record<string, number[]> = {};
  tickers.forEach((t, i) => {
    const r: number[] = [];
    for (let k = 1; k < dates.length; k++) {
      const p0 = maps[i].get(dates[k - 1])!, p1 = maps[i].get(dates[k])!;
      if (p0 > 0 && p1 > 0) r.push(p1 / p0 - 1);
    }
    out[t] = r;
  });
  // recorta a longitud común mínima
  const minLen = Math.min(...tickers.map((t) => out[t].length));
  tickers.forEach((t) => { out[t] = out[t].slice(-minLen); });
  return out;
}

export function Forecast() {
  const [assets, setAssets] = useState<AssetHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [horizon, setHorizon] = useState(252);
  const [whatIfTicker, setWhatIfTicker] = useState("");
  const [whatIfPct, setWhatIfPct] = useState(0);

  useEffect(() => {
    (async () => {
      const txns = (await getTransactions()).filter((t) => !t.fund_id);
      if (!txns.length) { setLoading(false); return; }
      const tickers = Array.from(new Set(txns.map((t) => t.ticker.toUpperCase())));
      const [prices, quotes, instruments, ca] = await Promise.all([
        getPrices(tickers), getQuotes(tickers), getInstruments(tickers), getCorporateActions(tickers),
      ]);
      const { prices: merged } = mergeValuation(tickers, prices, quotes);
      const positions = derivePositions(txns, merged, instruments, ca)
        .filter((p) => p.qty > 1e-9 && p.marketValue != null && p.marketValue > 0);
      const hist: Record<string, { as_of: string; close: number }[]> = {};
      await Promise.all(positions.map(async (p) => { hist[p.ticker] = await getPriceHistory(p.ticker); }));
      const rets = alignReturns(hist, positions.map((p) => p.ticker));
      setAssets(positions.map((p) => ({ ticker: p.ticker, valueUsd: p.marketValue ?? 0, returns: rets[p.ticker] ?? [] })));
    })().catch((e) => setErr(String(e))).finally(() => setLoading(false));
  }, []);

  const base = useMemo<ForecastResult | null>(() => assets.length ? forecast(assets) : null, [assets]);

  const whatIf = useMemo<ForecastResult | null>(() => {
    if (!assets.length || !whatIfTicker || whatIfPct === 0) return null;
    const adj = assets.map((a) => ({ ...a }));
    const i = adj.findIndex((a) => a.ticker === whatIfTicker);
    if (i < 0) return null;
    const delta = adj[i].valueUsd * (whatIfPct / 100);
    adj[i] = { ...adj[i], valueUsd: Math.max(0, adj[i].valueUsd + delta) };
    const n = adj[0]?.returns.length ?? 100;
    adj.push({ ticker: "EFECTIVO", valueUsd: Math.max(0, -delta), returns: new Array(n).fill(0) }); // compensa con efectivo
    return forecast(adj);
  }, [assets, whatIfTicker, whatIfPct]);

  if (loading) return <div className="grid gap-3">{[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-term-panel2" />)}</div>;
  if (err) return <p className="text-sm text-term-crit">Error: {err}</p>;
  if (!base) return <p className="text-sm text-term-muted">Sin posiciones para proyectar. Registra operaciones en «Mi Cartera».</p>;

  const hz = base.horizons.find((h) => h.days === horizon) ?? base.horizons[base.horizons.length - 1];
  const wiHz = whatIf?.horizons.find((h) => h.days === horizon);
  const bandSlice = base.band.filter((b) => b.day <= horizon);

  return (
    <div className="grid gap-4">
      <div className="rounded-lg border border-term-border bg-term-panel2 px-3 py-2 text-xs text-term-muted">
        <b className="text-term-fg">Proyección por simulación histórica</b> (bootstrap por bloques multivariante sobre {base.nObs} días reales,
        con correlaciones entre activos). <b>No es una predicción calibrada</b> ni usa los modelos experimentales A/B/C;
        es el rango de resultados si el futuro se pareciera a la distribución histórica reciente.
      </div>

      <Panel title="Proyección de la cartera">
        <div className="mb-2 flex flex-wrap gap-1">
          {base.horizons.map((h) => (
            <button key={h.days} onClick={() => setHorizon(h.days)}
              className={`rounded px-2.5 py-1 text-sm ${horizon === h.days ? "bg-term-accent text-term-bg" : "bg-term-panel2 text-term-muted"}`}>{h.label}</button>
          ))}
        </div>
        <ForecastChart band={bandSlice} current={base.currentValue} horizonDays={horizon} />
        <div className="mt-3 grid grid-cols-3 gap-2 text-center">
          <Scenario label="Desfavorable (p5)" val={hz.valP5} ret={hz.retP5} cur={base.currentValue} tone="text-term-crit" />
          <Scenario label="Central (mediana)" val={hz.valP50} ret={hz.retP50} cur={base.currentValue} tone="text-term-fg" />
          <Scenario label="Favorable (p95)" val={hz.valP95} ret={hz.retP95} cur={base.currentValue} tone="text-term-good" />
        </div>
        <p className="mt-2 text-sm text-term-muted">
          A <b>{hz.label}</b>: en el <b>50%</b> de los escenarios tu cartera queda entre {money(hz.valP25)} y {money(hz.valP75)}.
          Probabilidad de terminar por debajo de hoy: <b className={hz.probLoss > 0.5 ? "text-term-crit" : "text-term-fg"}>{(hz.probLoss * 100).toFixed(0)}%</b>.
          Pérdida en el peor 5% (VaR): <b className="text-term-crit">{money(hz.var95)}</b>.
        </p>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="¿Dónde está mi riesgo?">
          <p className="mb-2 text-xs text-term-muted">Volatilidad anual de la cartera: <b className="text-term-fg">{(base.annVol * 100).toFixed(1)}%</b> · Concentración (HHI): <b>{base.hhi.toFixed(2)}</b> · Top 5 posiciones: <b>{(base.top5WeightPct * 100).toFixed(0)}%</b></p>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs uppercase text-term-muted"><th className="py-1">Posición</th><th className="text-right">Peso</th><th className="text-right">% del riesgo</th></tr></thead>
            <tbody>
              {base.riskContrib.slice(0, 10).map((r) => (
                <tr key={r.ticker} className="border-b border-term-border last:border-0">
                  <td className="py-1.5 font-mono font-semibold">{r.ticker}</td>
                  <td className="text-right tabnum">{(r.weightPct * 100).toFixed(1)}%</td>
                  <td className="text-right tabnum">
                    <div className="flex items-center justify-end gap-1">
                      <div className="h-1.5 w-16 rounded bg-term-panel2"><div className="h-full rounded bg-term-accent" style={{ width: `${Math.min(100, r.riskPct * 100)}%` }} /></div>
                      {(r.riskPct * 100).toFixed(0)}%</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-[11px] text-term-faint">El % del riesgo (no del valor) indica qué posiciones mueven más tu cartera, considerando correlaciones.</p>
        </Panel>

        <Panel title="Simulador ¿qué pasa si…? (no modifica tu cartera)">
          <div className="flex flex-wrap items-end gap-2">
            <select value={whatIfTicker} onChange={(e) => setWhatIfTicker(e.target.value)} className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm">
              <option value="">Posición…</option>{assets.map((a) => <option key={a.ticker} value={a.ticker}>{a.ticker}</option>)}
            </select>
            <div className="flex-1">
              <input type="range" min={-100} max={100} step={5} value={whatIfPct} onChange={(e) => setWhatIfPct(Number(e.target.value))} className="w-full" />
              <div className="text-center text-xs text-term-muted">{whatIfPct > 0 ? "+" : ""}{whatIfPct}% {whatIfTicker && `(${money((assets.find((a) => a.ticker === whatIfTicker)?.valueUsd ?? 0) * whatIfPct / 100)})`} → efectivo</div>
            </div>
          </div>
          {wiHz && whatIf ? (
            <table className="mt-2 w-full text-sm">
              <thead><tr className="text-left text-xs uppercase text-term-muted"><th className="py-1">Métrica ({hz.label})</th><th className="text-right">Actual</th><th className="text-right">Simulada</th></tr></thead>
              <tbody>
                <Row k="Volatilidad anual" a={`${(base.annVol * 100).toFixed(1)}%`} b={`${(whatIf.annVol * 100).toFixed(1)}%`} better={whatIf.annVol < base.annVol} />
                <Row k="Prob. de pérdida" a={`${(hz.probLoss * 100).toFixed(0)}%`} b={`${(wiHz.probLoss * 100).toFixed(0)}%`} better={wiHz.probLoss < hz.probLoss} />
                <Row k="Escenario central" a={money(hz.valP50)} b={money(wiHz.valP50)} better={wiHz.valP50 > hz.valP50} />
                <Row k="Desfavorable (p5)" a={money(hz.valP5)} b={money(wiHz.valP5)} better={wiHz.valP5 > hz.valP5} />
              </tbody>
            </table>
          ) : <p className="mt-2 text-xs text-term-faint">Elige una posición y mueve el control para ver el efecto sobre riesgo y escenarios.</p>}
        </Panel>
      </div>

      {base.warnings.length > 0 && (
        <p className="text-xs text-term-warn">Limitaciones: {base.warnings.join(" ")}</p>
      )}
      <p className="text-[11px] text-term-faint">
        Conciliación: valor proyectado de base = {money(base.currentValue)} (= suma de tus posiciones). Horizontes en días bursátiles (21/63/126/252 ≈ 1/3/6/12 meses).
        Las correlaciones históricas capturan el co-movimiento entre tus ETFs solapados (p. ej. VOO y QQQ).
      </p>
    </div>
  );
}

function Scenario({ label, val, ret, cur, tone }: { label: string; val: number; ret: number; cur: number; tone: string }) {
  return (
    <div className="rounded-lg border border-term-border bg-term-panel2 px-2 py-2">
      <div className="text-[10px] uppercase text-term-muted">{label}</div>
      <div className={`text-base font-semibold tabnum ${tone}`}>{money(val)}</div>
      <div className={`text-xs tabnum ${ret >= 0 ? "text-term-good" : "text-term-crit"}`}>{ret >= 0 ? "+" : ""}{(ret * 100).toFixed(1)}% · {money(val - cur)}</div>
    </div>
  );
}

function Row({ k, a, b, better }: { k: string; a: string; b: string; better: boolean }) {
  return (
    <tr className="border-b border-term-border last:border-0">
      <td className="py-1.5">{k}</td>
      <td className="text-right tabnum text-term-muted">{a}</td>
      <td className={`text-right tabnum font-semibold ${better ? "text-term-good" : "text-term-crit"}`}>{b}</td>
    </tr>
  );
}

function ForecastChart({ band, current, horizonDays }: { band: { day: number; p5: number; p50: number; p95: number }[]; current: number; horizonDays: number }) {
  const W = 640, H = 220, padL = 56, padR = 12, padT = 12, padB = 24;
  if (band.length < 2) return <div className="h-[220px] rounded bg-term-panel2" />;
  const xs = band.map((b) => b.day);
  const allV = band.flatMap((b) => [b.p5, b.p95]).concat(current);
  const minV = Math.min(...allV) * 0.98, maxV = Math.max(...allV) * 1.02;
  const x = (d: number) => padL + ((d - xs[0]) / (xs[xs.length - 1] - xs[0])) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v - minV) / (maxV - minV)) * (H - padT - padB);
  const areaTop = band.map((b) => `${x(b.day)},${y(b.p95)}`).join(" ");
  const areaBot = band.slice().reverse().map((b) => `${x(b.day)},${y(b.p5)}`).join(" ");
  const median = band.map((b) => `${x(b.day)},${y(b.p50)}`).join(" ");
  const yticks = [minV, (minV + maxV) / 2, maxV];
  const months = Math.round(horizonDays / 21);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 240 }}>
      {yticks.map((v, i) => (
        <g key={i}>
          <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} stroke="currentColor" className="text-term-border" strokeWidth={0.5} />
          <text x={padL - 6} y={y(v) + 3} textAnchor="end" className="fill-term-faint" fontSize={9}>${(v / 1000).toFixed(1)}k</text>
        </g>
      ))}
      <line x1={padL} x2={W - padR} y1={y(current)} y2={y(current)} stroke="currentColor" className="text-term-muted" strokeWidth={0.8} strokeDasharray="3 3" />
      <polygon points={`${areaTop} ${areaBot}`} className="fill-term-accent" opacity={0.15} />
      <polyline points={median} fill="none" className="stroke-term-accent" strokeWidth={1.8} />
      {Array.from({ length: months + 1 }, (_, m) => m * 21 + 1).filter((d) => d <= horizonDays).map((d, i) => (
        <text key={i} x={x(d)} y={H - 8} textAnchor="middle" className="fill-term-faint" fontSize={9}>{i}m</text>
      ))}
    </svg>
  );
}
