import { useEffect, useMemo, useState } from "react";
import { Panel } from "../components/Panel";
import {
  getCorporateActions, getFundamentals, getInstruments, getPriceHistory, getPrices, getQuotes,
  getTransactions,
} from "../data";
import { derivePositions } from "../core/portfolio-tx";
import { mergeValuation } from "../core/price-source";
import { forecast, buildAssets, type ForecastResult, type PriceBarLite } from "../core/forecast";
import { FundamentalView, type FundRow } from "../components/FundamentalView";
import { valuateCompany } from "../core/fundamental";
import { computeCoverage, type CovItem } from "../core/coverage";
import type { FundamentalsPayload } from "../core/valuation";
import { money, pct } from "../format";

const COMMODITY_T = ["GLD", "SLV", "IAU", "PPLT", "PALL", "SGOL", "SIVR"];
function kindOf(ticker: string, assetClass: string | null): "equity" | "etf" | "commodity" {
  const ac = (assetClass ?? "").toLowerCase();
  if (COMMODITY_T.includes(ticker.toUpperCase()) || ac === "commodity") return "commodity";
  if (ac === "etf" || ac === "fund" || ac === "etn" || ac === "mutualfund") return "etf";
  return "equity";
}

type Bars = PriceBarLite[];

export function Forecast() {
  const [hist, setHist] = useState<Record<string, Bars>>({});
  const [valueMap, setValueMap] = useState<Record<string, number>>({});
  const [fundRows, setFundRows] = useState<FundRow[]>([]);
  const [fundamentals, setFundamentals] = useState<Record<string, FundamentalsPayload>>({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [view, setView] = useState<"riesgo" | "fundamental">("riesgo");
  const [horizon, setHorizon] = useState(252);
  const [drift, setDrift] = useState<"historical" | "neutral">("neutral");

  // simulador
  const [simTicker, setSimTicker] = useState("");
  const [simAction, setSimAction] = useState<"aumentar" | "reducir" | "vender" | "efectivo" | "comprar" | "aportar">("reducir");
  const [simAmount, setSimAmount] = useState(0);
  const [simFinance, setSimFinance] = useState<"autofinanciado" | "nuevo">("autofinanciado");
  const [newTicker, setNewTicker] = useState("");

  useEffect(() => {
    (async () => {
      const txns = (await getTransactions()).filter((t) => !t.fund_id);
      if (!txns.length) { setLoading(false); return; }
      const tickers = Array.from(new Set(txns.map((t) => t.ticker.toUpperCase())));
      const [prices, quotes, instruments, ca, funds] = await Promise.all([
        getPrices(tickers), getQuotes(tickers), getInstruments(tickers), getCorporateActions(tickers),
        getFundamentals(tickers),
      ]);
      const { prices: merged } = mergeValuation(tickers, prices, quotes);
      const positions = derivePositions(txns, merged, instruments, ca)
        .filter((p) => p.qty > 1e-9 && p.marketValue != null && p.marketValue > 0);
      const h: Record<string, Bars> = {};
      await Promise.all(positions.map(async (p) => { h[p.ticker] = await getPriceHistory(p.ticker); }));
      setHist(h);
      setValueMap(Object.fromEntries(positions.map((p) => [p.ticker, p.marketValue ?? 0])));
      setFundamentals(funds);
      setFundRows(positions.map((p) => ({
        ticker: p.ticker, name: p.name,
        sector: instruments[p.ticker]?.sector ?? null,
        assetClass: instruments[p.ticker]?.asset_class ?? p.asset_class ?? null,
        price: p.price, priceAsOf: p.priceAsOf, qty: p.qty, marketValue: p.marketValue,
      })));
    })().catch((e) => setErr(String(e))).finally(() => setLoading(false));
  }, []);

  const baseAssets = useMemo(() => buildAssets(hist, valueMap), [hist, valueMap]);
  const base = useMemo<ForecastResult | null>(() => baseAssets.length ? forecast(baseAssets, { drift }) : null, [baseAssets, drift]);
  const other = useMemo<ForecastResult | null>(() => baseAssets.length ? forecast(baseAssets, { drift: drift === "neutral" ? "historical" : "neutral" }) : null, [baseAssets, drift]);
  const win1y = useMemo<ForecastResult | null>(() => baseAssets.length ? forecast(baseAssets, { drift, windowDays: 252 }) : null, [baseAssets, drift]);

  // Escenario simulado
  const simValueMap = useMemo(() => {
    if (!simTicker && simAction !== "comprar" && simAction !== "aportar") return null;
    if (simAmount <= 0) return null;
    const m = { ...valueMap };
    const cashKey = "EFECTIVO";
    m[cashKey] = m[cashKey] ?? 0;
    const t = simAction === "comprar" ? newTicker.toUpperCase().trim() : simTicker;
    if (simAction === "aportar") { m[cashKey] += simAmount; return m; }
    if (!t) return null;
    if (simAction === "vender") { const v = m[t] ?? 0; m[t] = 0; m[cashKey] += v; return m; }
    if (simAction === "efectivo") { const d = Math.min(simAmount, m[t] ?? 0); m[t] = (m[t] ?? 0) - d; m[cashKey] += d; return m; }
    if (simAction === "reducir") {
      const d = Math.min(simAmount, m[t] ?? 0); m[t] = (m[t] ?? 0) - d;
      m[cashKey] += d; // lo vendido pasa a efectivo (autofinanciado)
      return m;
    }
    if (simAction === "aumentar" || simAction === "comprar") {
      m[t] = (m[t] ?? 0) + simAmount;
      if (simFinance === "autofinanciado") m[cashKey] = (m[cashKey] ?? 0) - simAmount; // desde efectivo
      return m;
    }
    return m;
  }, [valueMap, simTicker, simAction, simAmount, simFinance, newTicker]);

  // historial del nuevo ticker (para 'comprar')
  useEffect(() => {
    const t = newTicker.toUpperCase().trim();
    if (simAction === "comprar" && t && !hist[t]) {
      getPriceHistory(t).then((b) => { if (b.length) setHist((h) => ({ ...h, [t]: b })); }).catch(() => {});
    }
  }, [newTicker, simAction, hist]);

  const simResult = useMemo<ForecastResult | null>(() => {
    if (!simValueMap) return null;
    const a = buildAssets(hist, simValueMap);
    return a.length ? forecast(a, { drift }) : null;
  }, [simValueMap, hist, drift]);

  const coverage = useMemo(() => {
    if (!fundRows.length) return null;
    const items: CovItem[] = fundRows.map((r) => {
      const bars = (hist[r.ticker] ?? hist[r.ticker.toUpperCase()])?.length ?? 0;
      const kind = kindOf(r.ticker, r.assetClass);
      const fundOk = kind === "equity" && valuateCompany({
        ticker: r.ticker, name: r.name, sector: r.sector, price: r.price, priceAsOf: r.priceAsOf,
        f: fundamentals[r.ticker.toUpperCase()] ?? fundamentals[r.ticker],
      }).available;
      return {
        ticker: r.ticker, marketValue: r.marketValue ?? 0,
        hasPrice: r.price != null, statOk: bars >= 61, fundOk, asOf: r.priceAsOf,
      };
    });
    return computeCoverage(items);
  }, [fundRows, hist, fundamentals]);

  if (loading) return <div className="grid gap-3">{[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-term-panel2" />)}</div>;
  if (err) return <p className="text-sm text-term-crit">Error: {err}</p>;

  const perspective = (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-term-faint">Perspectiva:</span>
      <div className="flex gap-1">
        <button onClick={() => setView("riesgo")}
          className={`rounded px-3 py-1.5 text-sm ${view === "riesgo" ? "bg-term-accent text-term-bg" : "bg-term-panel2 text-term-muted"}`}>A · Riesgo histórico</button>
        <button onClick={() => setView("fundamental")}
          className={`rounded px-3 py-1.5 text-sm ${view === "fundamental" ? "bg-term-accent text-term-bg" : "bg-term-panel2 text-term-muted"}`}>B · Valoración fundamental</button>
      </div>
    </div>
  );
  const twoEngines = (
    <p className="text-xs text-term-faint">
      Dos motores independientes. <b className="text-term-fg">A (riesgo histórico):</b> «¿qué resultados podría experimentar mi cartera si los retornos se parecen a los históricos?» (bootstrap, correlaciones).
      <b className="text-term-fg"> B (valoración fundamental):</b> «¿cuánto podrían valer mis empresas bajo escenarios económicos?» (EPS, múltiplos). No se combinan en una sola cifra.
    </p>
  );

  const coveragePanel = coverage && coverage.total > 0 && (
    <div className="rounded-lg border border-term-border bg-term-panel2 p-3">
      <div className="mb-2 text-sm font-semibold text-term-fg">Cobertura de tu cartera (ponderada por patrimonio)</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <CovTile label="Con precio" value={coverage.pricePct} tone="text-term-fg" />
        <CovTile label="Con simulación estadística" value={coverage.statPct} tone={coverage.statSufficient ? "text-term-good" : "text-term-warn"} />
        <CovTile label="Con valoración fundamental" value={coverage.fundPct} tone={coverage.fundSufficient ? "text-term-good" : "text-term-muted"} />
        <CovTile label="Sin cobertura (riesgo)" value={coverage.uncoveredPct} tone={coverage.uncoveredPct > 0.2 ? "text-term-crit" : "text-term-muted"} />
      </div>
      <p className="mt-2 text-[11px] text-term-faint">
        {coverage.oldestAsOf && <>Dato más antiguo relevante: {coverage.oldestAsOf}. </>}
        {coverage.topStatGap.length > 0 && <>Más pesan en el hueco estadístico: {coverage.topStatGap.map((g) => `${g.ticker} (${pct(g.weight)})`).join(", ")}. </>}
        Porcentajes sobre {money(coverage.total)} de patrimonio con precio.
      </p>
    </div>
  );

  const partialBanner = coverage && !coverage.statSufficient && (
    <div className="rounded-lg border border-term-warn/40 bg-term-warn/10 px-3 py-2 text-xs text-term-warn">
      <b>Proyección PARCIAL.</b> Solo el {pct(coverage.statPct)} del patrimonio tiene simulación estadística;
      el {pct(coverage.uncoveredPct)} restante se mantiene a <b>valor fijo</b> (supuesto técnico, no una proyección
      y <b>no</b> implica volatilidad cero). Las bandas reflejan el riesgo solo de la parte cubierta y
      <b> no representan toda la cartera</b> (umbral {pct(coverage.statThreshold)}).
    </div>
  );

  if (view === "fundamental") {
    return (
      <div className="grid gap-4">
        {perspective}
        {twoEngines}
        {coveragePanel}
        <FundamentalView rows={fundRows} fundamentals={fundamentals} />
      </div>
    );
  }

  if (!base) return <div className="grid gap-4">{perspective}<p className="text-sm text-term-muted">Sin posiciones para proyectar. Registra operaciones en «Mi Cartera».</p></div>;
  if (!base.horizons.length) return <div className="grid gap-4">{perspective}<p className="text-sm text-term-warn">No hay historial de precios suficiente (≥60 días) en tus posiciones para proyectar. {base.warnings.join(" ")}</p></div>;

  const hz = base.horizons.find((h) => h.days === horizon) ?? base.horizons[base.horizons.length - 1];
  const bandSlice = base.band.filter((b) => b.day <= horizon);
  const simHz = simResult?.horizons.find((h) => h.days === horizon);

  return (
    <div className="grid gap-4">
      {perspective}
      {twoEngines}
      {coveragePanel}
      {partialBanner}
      <div className="rounded-lg border border-term-border bg-term-panel2 px-3 py-2 text-xs text-term-muted">
        <b className="text-term-fg">Proyección por simulación histórica</b> (bootstrap por bloques multivariante, {base.nObs} días reales, con correlaciones).
        <b> No es predicción calibrada</b> ni usa A/B/C. Precios ajustados por splits y dividendos (cierre ajustado de Yahoo). Sin look-ahead.
        El modo <b>Neutral</b> quita la deriva histórica (retornos centrados en 0) para no extrapolar el mercado alcista reciente.
      </div>

      <Panel title="Proyección de la cartera">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <div className="flex gap-1">
            {base.horizons.map((h) => (
              <button key={h.days} onClick={() => setHorizon(h.days)}
                className={`rounded px-2.5 py-1 text-sm ${horizon === h.days ? "bg-term-accent text-term-bg" : "bg-term-panel2 text-term-muted"}`}>{h.label}</button>
            ))}
          </div>
          <div className="ml-auto flex gap-1 text-xs">
            {(["neutral", "historical"] as const).map((d) => (
              <button key={d} onClick={() => setDrift(d)}
                className={`rounded px-2 py-1 ${drift === d ? "bg-term-panel text-term-fg ring-1 ring-term-accent" : "bg-term-panel2 text-term-muted"}`}>
                {d === "neutral" ? "Neutral (sin deriva)" : "Histórico (con deriva)"}</button>
            ))}
          </div>
        </div>
        <ForecastChart band={bandSlice} current={base.currentValue} horizonDays={horizon} />
        <div className="mt-3 grid grid-cols-3 gap-2 text-center">
          <Scenario label="Desfavorable (p5)" val={hz.valP5} ret={hz.retP5} cur={base.currentValue} tone="text-term-crit" />
          <Scenario label="Central (mediana)" val={hz.valP50} ret={hz.retP50} cur={base.currentValue} tone="text-term-fg" />
          <Scenario label="Favorable (p95)" val={hz.valP95} ret={hz.retP95} cur={base.currentValue} tone="text-term-good" />
        </div>
        <p className="mt-2 text-sm text-term-muted">
          A <b>{hz.label}</b> ({drift === "neutral" ? "neutral" : "histórico"}): el 50% central cae entre {money(hz.valP25)} y {money(hz.valP75)}.
          Prob. de terminar bajo hoy: <b className={hz.probLoss > 0.5 ? "text-term-crit" : "text-term-fg"}>{(hz.probLoss * 100).toFixed(0)}%</b>.
          VaR (peor 5%): <b className="text-term-crit">{money(hz.var95)}</b>.
        </p>
        {other && (
          <p className="mt-1 text-xs text-term-faint">
            Comparación {drift === "neutral" ? "con deriva histórica" : "neutral sin deriva"} a {hz.label}: mediana {money(other.horizons.find((h) => h.days === horizon)?.valP50 ?? 0)}
            {" "}· el sesgo alcista de la ventana explica la diferencia. {win1y && `Sensibilidad a ventana 1 año: vol ${(win1y.annVol * 100).toFixed(0)}% vs ${(base.annVol * 100).toFixed(0)}% (2 años).`}
          </p>
        )}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="¿Dónde está mi riesgo? (por instrumento)">
          <p className="mb-2 text-xs text-term-muted">Vol. anual: <b className="text-term-fg">{(base.annVol * 100).toFixed(1)}%</b> · Concentración HHI: <b>{base.hhi.toFixed(2)}</b> (≈ {base.effectiveN.toFixed(1)} posiciones efectivas) · Top 5: <b>{(base.top5WeightPct * 100).toFixed(0)}%</b></p>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs uppercase text-term-muted"><th className="py-1">Posición</th><th className="text-right">Peso</th><th className="text-right">% del riesgo</th></tr></thead>
            <tbody>
              {base.riskContrib.slice(0, 10).map((r) => (
                <tr key={r.ticker} className="border-b border-term-border last:border-0">
                  <td className="py-1.5 font-mono font-semibold">{r.ticker}</td>
                  <td className="text-right tabnum">{(r.weightPct * 100).toFixed(1)}%</td>
                  <td className="text-right tabnum">
                    <div className="flex items-center justify-end gap-1">
                      <div className="h-1.5 w-16 rounded bg-term-panel2"><div className={`h-full rounded ${r.riskPct < 0 ? "bg-term-good" : "bg-term-accent"}`} style={{ width: `${Math.min(100, Math.abs(r.riskPct) * 100)}%` }} /></div>
                      <span className={r.riskPct < 0 ? "text-term-good" : ""}>{(r.riskPct * 100).toFixed(0)}%</span></div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-[11px] text-term-faint">% del riesgo (varianza) vía covarianzas/correlaciones; suma 100% y admite valores negativos (coberturas). Es exposición por <b>instrumento</b>; la exposición económica subyacente está en X-Ray (son vistas distintas).</p>
        </Panel>

        <Panel title="Simulador ¿qué pasa si…? (no modifica tu cartera)">
          <div className="grid gap-2">
            <div className="flex flex-wrap gap-1 text-xs">
              {(["reducir", "aumentar", "vender", "efectivo", "comprar", "aportar"] as const).map((a) => (
                <button key={a} onClick={() => setSimAction(a)} className={`rounded px-2 py-1 ${simAction === a ? "bg-term-accent text-term-bg" : "bg-term-panel2 text-term-muted"}`}>{a}</button>
              ))}
            </div>
            <div className="flex flex-wrap items-end gap-2">
              {simAction === "comprar"
                ? <input placeholder="Ticker a comprar (ej. ASML)" value={newTicker} onChange={(e) => setNewTicker(e.target.value)} className={inp} />
                : simAction !== "aportar" && (
                  <select value={simTicker} onChange={(e) => setSimTicker(e.target.value)} className={inp}>
                    <option value="">Posición…</option>{baseAssets.filter((a) => a.ticker !== "EFECTIVO").map((a) => <option key={a.ticker} value={a.ticker}>{a.ticker}</option>)}
                  </select>)}
              {simAction !== "vender" && <input type="number" min={0} step={500} placeholder="Monto USD" value={simAmount || ""} onChange={(e) => setSimAmount(Number(e.target.value))} className={`${inp} w-32`} />}
              {(simAction === "aumentar" || simAction === "comprar") && (
                <select value={simFinance} onChange={(e) => setSimFinance(e.target.value as "autofinanciado" | "nuevo")} className={inp}>
                  <option value="autofinanciado">desde efectivo</option><option value="nuevo">capital nuevo</option>
                </select>)}
            </div>
          </div>
          {simHz && simResult ? (
            <table className="mt-2 w-full text-sm">
              <thead><tr className="text-left text-xs uppercase text-term-muted"><th className="py-1">Métrica ({hz.label})</th><th className="text-right">Actual</th><th className="text-right">Simulada</th></tr></thead>
              <tbody>
                <Row k="Valor de cartera" a={money(base.currentValue)} b={money(simResult.currentValue)} better={simResult.currentValue >= base.currentValue} />
                <Row k="Volatilidad anual" a={`${(base.annVol * 100).toFixed(1)}%`} b={`${(simResult.annVol * 100).toFixed(1)}%`} better={simResult.annVol < base.annVol} />
                <Row k="Concentración (pos. efectivas)" a={base.effectiveN.toFixed(1)} b={simResult.effectiveN.toFixed(1)} better={simResult.effectiveN > base.effectiveN} />
                <Row k="Prob. de pérdida" a={`${(hz.probLoss * 100).toFixed(0)}%`} b={`${(simHz.probLoss * 100).toFixed(0)}%`} better={simHz.probLoss < hz.probLoss} />
                <Row k="Central (p50)" a={money(hz.valP50)} b={money(simHz.valP50)} better={simHz.valP50 > hz.valP50} />
                <Row k="Desfavorable (p5)" a={money(hz.valP5)} b={money(simHz.valP5)} better={simHz.valP5 > hz.valP5} />
                <Row k="Favorable (p95)" a={money(hz.valP95)} b={money(simHz.valP95)} better={simHz.valP95 > hz.valP95} />
              </tbody>
            </table>
          ) : <p className="mt-2 text-xs text-term-faint">Elige una operación y un monto. «Autofinanciado» mueve dinero desde/hacia efectivo (cartera constante); «capital nuevo» cambia el valor total. No se tocan tus transacciones.</p>}
          {simResult?.warnings.length ? <p className="mt-1 text-[11px] text-term-warn">{simResult.warnings.join(" ")}</p> : null}
        </Panel>
      </div>

      {base.warnings.length > 0 && <p className="text-xs text-term-warn">Limitaciones: {base.warnings.join(" ")}</p>}
      <p className="text-[11px] text-term-faint">
        Conciliación: base = {money(base.currentValue)} (= suma de posiciones). Horizontes en días bursátiles. Las correlaciones capturan el solapamiento (VOO/QQQ).
        Percentiles de bootstrap = rango de resultados históricos, no probabilidades predictivas calibradas.
      </p>
    </div>
  );
}

const inp = "rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm text-term-fg";

function CovTile({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded-lg border border-term-border bg-term-panel px-2 py-2">
      <div className="text-[10px] uppercase text-term-muted">{label}</div>
      <div className={`text-lg font-semibold tabnum ${tone}`}>{pct(value)}</div>
      <div className="mt-1 h-1.5 w-full rounded bg-term-panel2"><div className={`h-full rounded ${tone.replace("text-", "bg-")}`} style={{ width: `${Math.min(100, value * 100)}%` }} /></div>
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
