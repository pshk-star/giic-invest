import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Panel } from "../components/Panel";
import {
  getCorporateActions, getFundamentals, getInstruments, getLatestRun, getLatestScan, getPrices,
  getPriceHistory, getPredictionsByTicker, getQuotes, getTransactions,
  type PredictionRow, type PriceBar, type QuoteRow, type ScanRow,
} from "../data";
import { QuoteView } from "../components/Quote";
import { PriceChart } from "../components/PriceChart";
import { derivePositions, portfolioTotals } from "../core/portfolio-tx";
import { buildAssets, forecast } from "../core/forecast";
import {
  type FundamentalsPayload, type ScanFactors, factorExplanation, fairValueByFcfYield,
  fairValueByPE, impliedFcfGrowth, missingFundamentals, peerMedian, riskFlags,
} from "../core/valuation";
import { money, num, pct } from "../format";

const EMPTY_F: FundamentalsPayload = {
  pe_ttm: null, pe_forward: null, ev_ebitda: null, fcf_yield: null, roic: null, roe: null,
  rev_growth_yoy: null, eps_growth_yoy: null, net_margin: null, debt_to_equity: null, market_cap: null,
};

const todayISO = () => new Date().toISOString().slice(0, 10);

function Bar({ v, tone = "bg-term-accent" }: { v: number; tone?: string }) {
  return (
    <div className="h-1.5 w-full rounded bg-term-panel2">
      <div className={`h-full rounded ${tone}`} style={{ width: `${Math.max(0, Math.min(100, v))}%` }} />
    </div>
  );
}

// Proyección estadística INDIVIDUAL: disponible para CUALQUIER acción con historial
// suficiente, independiente del universo A/B/C, de EDGAR y de los fundamentales.
// Misma metodología que Portfolio Forecast (bootstrap por bloques sobre retornos
// ajustados). Es una distribución CONDICIONADA a supuestos históricos, no una
// predicción de rendimiento demostrado.
function StatProjection({ ticker, bars, price }: { ticker: string; bars: PriceBar[]; price: number | null }) {
  const [horizon, setHorizon] = useState(252);
  const [drift, setDrift] = useState<"neutral" | "historical">("neutral");
  const result = useMemo(() => {
    if (!price || bars.length < 61) return null;
    const assets = buildAssets({ [ticker]: bars }, { [ticker]: price });
    return assets.length ? forecast(assets, { drift }) : null;
  }, [ticker, bars, price, drift]);

  return (
    <Panel title="Proyección estadística individual (B · simulación histórica)">
      <p className="mb-2 text-xs text-term-muted">
        Simulación de la distribución de resultados de <b>{ticker}</b> a partir de sus <b>precios históricos ajustados</b>
        (bootstrap por bloques; misma metodología que Portfolio Forecast). Independiente del modelo A/B/C y de los
        fundamentales. Es una <b>distribución condicionada a supuestos históricos</b>, no una predicción validada.
      </p>
      {!price ? (
        <p className="text-sm text-term-warn">Sin precio actual: no se puede anclar la proyección.</p>
      ) : bars.length < 61 ? (
        <p className="text-sm text-term-warn">Historial insuficiente ({bars.length} sesiones; se requieren ≥61). No se proyecta.</p>
      ) : !result || !result.horizons.length ? (
        <p className="text-sm text-term-warn">No fue posible proyectar con el historial disponible.</p>
      ) : (
        <StatProjectionBody result={result} price={price} horizon={horizon} setHorizon={setHorizon} drift={drift} setDrift={setDrift} />
      )}
    </Panel>
  );
}

function StatProjectionBody({ result, price, horizon, setHorizon, drift, setDrift }: {
  result: ReturnType<typeof forecast>; price: number; horizon: number;
  setHorizon: (n: number) => void; drift: "neutral" | "historical"; setDrift: (d: "neutral" | "historical") => void;
}) {
  const hz = result.horizons.find((h) => h.days === horizon) ?? result.horizons[result.horizons.length - 1];
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {result.horizons.map((h) => (
            <button key={h.days} onClick={() => setHorizon(h.days)}
              className={`rounded px-2.5 py-1 text-sm ${horizon === h.days ? "bg-term-accent text-term-bg" : "bg-term-panel2 text-term-muted"}`}>{h.label}</button>
          ))}
        </div>
        <div className="ml-auto flex gap-1 text-xs">
          {(["neutral", "historical"] as const).map((d) => (
            <button key={d} onClick={() => setDrift(d)}
              className={`rounded px-2 py-1 ${drift === d ? "bg-term-panel text-term-fg ring-1 ring-term-accent" : "bg-term-panel2 text-term-muted"}`}>
              {d === "neutral" ? "Sin deriva" : "Con deriva histórica"}</button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center">
        {([["Desfavorable (P5)", hz.valP5, hz.retP5, "text-term-crit"], ["Central (P50)", hz.valP50, hz.retP50, "text-term-fg"], ["Favorable (P95)", hz.valP95, hz.retP95, "text-term-good"]] as const).map(([label, v, r, tone]) => (
          <div key={label} className="rounded-lg border border-term-border bg-term-panel2 px-2 py-2">
            <div className="text-[10px] uppercase text-term-muted">{label}</div>
            <div className={`text-base font-semibold tabnum ${tone}`}>{money(v)}</div>
            <div className={`text-xs tabnum ${r >= 0 ? "text-term-good" : "text-term-crit"}`}>{r >= 0 ? "+" : ""}{pct(r)}</div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-term-muted">
        <span>Precio ancla: <b className="text-term-fg">{money(price)}</b></span>
        <span>Volatilidad anual: <b className="text-term-fg">{pct(result.annVol)}</b></span>
        <span>Prob. de pérdida a {hz.label}: <b className={hz.probLoss > 0.5 ? "text-term-crit" : "text-term-fg"}>{pct(hz.probLoss)}</b></span>
        <span>VaR 5%: <b className="text-term-crit">{money(hz.var95)}</b></span>
        <span>Historial: <b className="text-term-fg">{result.nObs}</b> sesiones</span>
      </div>
      <p className="text-[11px] text-term-faint">
        Supuestos: compra y mantenimiento, sin rebalanceo; el muestreo por bloques preserva autocorrelación corta.
        «Sin deriva» centra los retornos en 0 (no extrapola el mercado alcista reciente). Los percentiles son rango de
        resultados históricos, <b>no</b> probabilidades predictivas calibradas ni rendimiento demostrado.
      </p>
    </div>
  );
}

function Metric({ label, value, help }: { label: string; value: string; help?: string }) {
  return (
    <div className="rounded-lg border border-term-border bg-term-panel2 p-2.5">
      <div className="text-[10px] uppercase tracking-wide text-term-faint">{label}</div>
      <div className="font-mono text-base tabnum text-term-fg">{value}</div>
      {help && <div className="text-[10px] text-term-faint">{help}</div>}
    </div>
  );
}

export function StockFiche({ ticker: rawTicker, embedded = false }: { ticker: string; embedded?: boolean }) {
  const ticker = (rawTicker ?? "").toUpperCase();
  const [preds, setPreds] = useState<PredictionRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [assetClass, setAssetClass] = useState<string | null>(null);
  const [exchange, setExchange] = useState<string | null>(null);
  const [sector, setSector] = useState<string | null>(null);
  const [price, setPrice] = useState<number | null>(null);
  const [priceAsOf, setPriceAsOf] = useState<string | null>(null);
  const [quote, setQuote] = useState<QuoteRow | null>(null);
  const [hist, setHist] = useState<PriceBar[]>([]);
  const [spy, setSpy] = useState<PriceBar[]>([]);
  const [qqq, setQqq] = useState<PriceBar[]>([]);
  const [fund, setFund] = useState<FundamentalsPayload>(EMPTY_F);
  const [peers, setPeers] = useState<FundamentalsPayload[]>([]);
  const [peerCount, setPeerCount] = useState(0);
  const [companyScan, setCompanyScan] = useState<ScanRow | null>(null);
  const [scanAsOf, setScanAsOf] = useState<string | null>(null);
  const [held, setHeld] = useState<{ weight: number; qty: number } | null>(null);
  const [reqReturn, setReqReturn] = useState(0.09);

  useEffect(() => {
    (async () => {
      setLoaded(false); setErr(null);
      const [scanAll, instMap, priceMap, quoteMap, run, txns, h, hSpy, hQqq, pr] = await Promise.all([
        getLatestScan(), getInstruments([ticker]), getPrices([ticker]), getQuotes([ticker]),
        getLatestRun(), getTransactions(),
        getPriceHistory(ticker), getPriceHistory("SPY"), getPriceHistory("QQQ"),
        getPredictionsByTicker(ticker),
      ]);
      setPreds(pr);
      setQuote(quoteMap[ticker] ?? null);
      setHist(h); setSpy(hSpy); setQqq(hQqq);
      const meta = instMap[ticker];
      const cScan = scanAll.find((r) => r.ticker.toUpperCase() === ticker) ?? null;
      const sec = meta?.sector ?? cScan?.sector ?? null;
      setName(meta?.name ?? null);
      setAssetClass(meta?.asset_class ?? null);
      setExchange(meta?.exchange ?? null);
      setSector(sec);
      setPrice(priceMap[ticker]?.close ?? null);
      setPriceAsOf(priceMap[ticker]?.as_of ?? null);
      setCompanyScan(cScan);
      setScanAsOf(run?.as_of ?? null);

      const peerTickers = scanAll.filter((r) => r.sector === sec && r.ticker.toUpperCase() !== ticker).map((r) => r.ticker);
      setPeerCount(peerTickers.length);
      const fundMap = await getFundamentals([ticker, ...peerTickers]);
      setFund(fundMap[ticker] ?? EMPTY_F);
      setPeers(peerTickers.map((t) => fundMap[t]).filter((x): x is FundamentalsPayload => !!x));

      // ¿Está en tu cartera? Peso real.
      if (txns.some((t) => t.ticker.toUpperCase() === ticker)) {
        const all = Array.from(new Set(txns.map((t) => t.ticker.toUpperCase())));
        const [pr, inst, ca] = await Promise.all([getPrices(all), getInstruments(all), getCorporateActions(all)]);
        const pos = derivePositions(txns, pr, inst, ca);
        const totals = portfolioTotals(pos);
        const mine = pos.find((p) => p.ticker === ticker && p.qty > 1e-9);
        if (mine) setHeld({ weight: totals.weights[ticker] ?? 0, qty: mine.qty });
      }
      setLoaded(true);
    })().catch((e) => setErr(String(e)));
  }, [ticker]);

  const isEtf = ["etf", "fund", "etn", "mutualfund"].includes((assetClass ?? "").toLowerCase());

  const peerPE = useMemo(() => peerMedian(peers, "pe_ttm"), [peers]);
  const peerFcf = useMemo(() => peerMedian(peers, "fcf_yield"), [peers]);
  const peerRoe = useMemo(() => peerMedian(peers, "roe", false), [peers]);
  const peerMargin = useMemo(() => peerMedian(peers, "net_margin", false), [peers]);
  const peerGrowth = useMemo(() => peerMedian(peers, "rev_growth_yoy", false), [peers]);

  const scanFactors: ScanFactors | null = companyScan
    ? {
        composite: companyScan.composite,
        value: companyScan.factor_value, quality: companyScan.factor_quality,
        growth: companyScan.factor_growth, momentum: companyScan.factor_momentum,
        low_risk: companyScan.factor_low_risk, tags: companyScan.tags ?? [],
      }
    : null;

  const fvPE = fairValueByPE(fund.pe_ttm, peerPE);
  const fvFcf = fairValueByFcfYield(fund.fcf_yield, peerFcf);
  const impliedG = impliedFcfGrowth(fund.fcf_yield, reqReturn);
  const risks = riskFlags(fund, peerPE, scanFactors);
  const missing = missingFundamentals(fund);

  if (err) return <p className="text-sm text-term-crit">{err}</p>;
  if (!loaded) return <p className="text-sm text-term-muted">Cargando {ticker}…</p>;

  const factors: Array<[string, number | null]> = [
    ["value", companyScan?.factor_value ?? null], ["quality", companyScan?.factor_quality ?? null],
    ["growth", companyScan?.factor_growth ?? null], ["momentum", companyScan?.factor_momentum ?? null],
    ["low_risk", companyScan?.factor_low_risk ?? null],
  ];

  return (
    <div className="grid gap-4">
      {!embedded && <Link to="/research" className="text-xs text-term-muted hover:text-term-fg">← Research</Link>}

      <Panel title="Ficha de la empresa">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <div className="font-mono text-2xl font-bold text-term-fg">{ticker}</div>
            <div className="text-sm text-term-muted">
              {name ?? "Nombre no disponible"} · {sector ?? "sector n/d"} · {assetClass ?? "?"}{exchange ? ` · ${exchange}` : ""}
            </div>
          </div>
          <div className="text-right">
            {quote
              ? <QuoteView q={quote} />
              : <>
                  <div className="font-mono text-xl tabnum text-term-fg">{price !== null ? money(price) : <span className="text-term-warn">pendiente</span>}</div>
                  <div className="text-[10px] text-term-faint">{priceAsOf ? `precio de mercado · al ${priceAsOf}` : "sin precio aún"}</div>
                </>}
          </div>
        </div>
        {held && (
          <p className="mt-2 text-xs text-term-good">
            En tu cartera: {num(held.qty, 2)} unidades · peso {pct(held.weight)} del total.
          </p>
        )}
      </Panel>

      <Panel title="Precio histórico">
        <PriceChart
          primary={{ label: ticker, bars: hist, color: "#5eead4" }}
          benchmarks={[
            { label: "S&P 500 (SPY)", bars: spy, color: "#94a3b8" },
            { label: "Nasdaq-100 (QQQ)", bars: qqq, color: "#fbbf24" },
          ]}
        />
        {hist.length > 0 && (
          <p className="mt-1 text-[10px] text-term-faint">
            Cierre ajustado (splits y dividendos). Último punto: {money(hist[hist.length - 1].close)} al {hist[hist.length - 1].as_of}.
            El «precio de mercado» de arriba es la cotización del día ({priceAsOf ?? "s/f"}); por eso puede diferir del último cierre del gráfico.
          </p>
        )}
      </Panel>

      <StatProjection ticker={ticker} bars={hist} price={price} />


      <Panel title="Proyecciones del modelo (experimental)">
        {preds.length === 0 ? (
          <div className="text-sm">
            <p className="text-term-warn">Sin cobertura del modelo experimental A/B/C para {ticker}.</p>
            <p className="mt-1 text-term-muted">
              <b>Causa concreta:</b> {ticker} no está en el universo del modelo (universe.py), definido como
              acciones estadounidenses líquidas; los emisores extranjeros (ASML, TSM) quedan fuera por diseño.
              Tiene historial de precios y {fund.pe_ttm != null || fund.roe != null ? "ya cuenta con fundamentales reales (abajo)" : "fundamentales según disponibilidad"}.
              Incluirlo en A/B/C exigiría una <b>emisión nueva y validada</b> (no se modifican las 309 predicciones
              registradas ni se generan predicciones artificiales).
            </p>
          </div>
        ) : (
          <>
            <div className="mb-2 rounded-lg border border-term-warn/40 bg-term-warn/10 px-3 py-2 text-xs text-term-warn">
              <strong>EXPERIMENTAL · NO VALIDADO.</strong> El retorno es <b>relativo</b> al universo equiponderado,
              no el retorno absoluto del activo. Por eso <b>no se deriva un precio objetivo</b>.
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase text-term-muted">
                    <th className="py-1.5">Horizonte</th><th>Modelo</th>
                    <th className="text-right">Retorno rel. previsto</th>
                    <th className="text-right">Percentil</th><th>Evalúa en</th><th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {preds.map((p) => {
                    const matured = p.evaluate_on <= todayISO();
                    const rr = p.prediction?.rel_return;
                    const prc = p.prediction?.pct_rank;
                    return (
                      <tr key={`${p.model_version}-${p.horizon_sessions}`} className="border-b border-term-border last:border-0">
                        <td className="py-2 tabnum">{p.horizon_sessions} ses.</td>
                        <td className="text-term-muted">{p.model_name} <span className="text-term-faint">{p.model_version}</span></td>
                        <td className={`text-right tabnum ${rr != null && rr >= 0 ? "text-term-good" : "text-term-crit"}`}>
                          {rr != null ? `${rr >= 0 ? "+" : ""}${(rr * 100).toFixed(2)}%` : "—"}
                        </td>
                        <td className="text-right tabnum">{prc != null ? num(prc * 100, 0) : "—"}</td>
                        <td className="tabnum">{p.evaluate_on}</td>
                        <td>{matured
                          ? <span className="text-term-good">madura</span>
                          : <span className="text-term-muted">pendiente</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mt-2 grid gap-1 text-xs text-term-faint">
              <p><b className="text-term-muted">Cómo leerlo:</b> "+2%" quiere decir que el modelo prevé que {ticker} rinda ~2 puntos porcentuales por encima del promedio del universo en ese horizonte — no que suba 2% en absoluto.</p>
              <p><b className="text-term-muted">Sin precio objetivo:</b> una estimación relativa no define un precio absoluto; convertirla lo sería incorrecto.</p>
              <p><b className="text-term-muted">Percentil:</b> posición del activo dentro del universo ese día (100 = mejor previsto).</p>
              <p><b className="text-term-muted">Limitaciones:</b> modelos A/B experimentales, sin ventaja estadística demostrada sobre el equiponderado; universo con sesgo de supervivencia; evaluación prospectiva aún sin madurar.</p>
            </div>
          </>
        )}
      </Panel>

      {isEtf ? (
        <Panel title="Instrumento diversificado (ETF)">
          <p className="text-sm text-term-muted">
            Es un ETF: no aplican fundamentales por empresa (EDGAR no los publica). La valoración
            relativa por múltiplos no corresponde. Abajo sí ves los factores del scanner y el precio.
          </p>
        </Panel>
      ) : (
        <>
          <Panel title="Fundamentales (reales, de SEC EDGAR)">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Metric label="P/E (anual)" value={fund.pe_ttm !== null ? `${num(fund.pe_ttm, 1)}×` : "—"} help={fund.as_of ? `EPS del ejercicio ${fund.as_of}, no TTM` : "sobre EPS del último ejercicio, no TTM"} />
              <Metric label="FCF yield" value={pct(fund.fcf_yield)} />
              <Metric label="ROE" value={pct(fund.roe)} />
              <Metric label="Margen neto" value={pct(fund.net_margin)} />
              <Metric label="Crec. ingresos" value={pct(fund.rev_growth_yoy)} help="interanual" />
              <Metric label="Crec. EPS" value={pct(fund.eps_growth_yoy)} help="interanual" />
              <Metric label="Deuda/Capital" value={fund.debt_to_equity !== null ? `${num(fund.debt_to_equity, 2)}×` : "—"} />
              <Metric label="Market cap" value={fund.market_cap !== null ? money(fund.market_cap) : "—"} />
            </div>
            <p className="mt-2 text-[11px] text-term-faint">
              Fuente: SEC EDGAR ({fund.taxonomy ?? "companyfacts"}{fund.currency ? ` · divisa de reporte ${fund.currency}` : ""}){fund.as_of ? ` · ejercicio anual al ${fund.as_of}` : ""}.
              {fund.currency && fund.currency !== "USD" && " Márgenes, ROE y crecimientos son adimensionales (correctos en cualquier divisa); P/E y market cap se expresan contra el precio en USD."}
            </p>
            {missing.length > 0 && (
              <p className="mt-2 text-xs text-term-warn">No disponibles gratis: {missing.join(", ")}.</p>
            )}
          </Panel>

          <Panel title="Valoración relativa (comparables del sector · supuestos transparentes)">
            {peerCount === 0 ? (
              <p className="text-sm text-term-muted">Sin pares en el universo del scanner para este sector: no se puede comparar.</p>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[480px] text-sm">
                    <thead>
                      <tr className="border-b border-term-border text-left text-xs uppercase text-term-muted">
                        <th className="py-2">Métrica</th><th className="text-right">{ticker}</th>
                        <th className="text-right">Mediana sector</th>
                      </tr>
                    </thead>
                    <tbody>
                      <CompRow label="P/E ttm" a={fund.pe_ttm} b={peerPE} suffix="×" />
                      <CompRow label="FCF yield" a={fund.fcf_yield} b={peerFcf} isPct />
                      <CompRow label="ROE" a={fund.roe} b={peerRoe} isPct />
                      <CompRow label="Margen neto" a={fund.net_margin} b={peerMargin} isPct />
                      <CompRow label="Crec. ingresos" a={fund.rev_growth_yoy} b={peerGrowth} isPct />
                    </tbody>
                  </table>
                </div>
                <p className="mt-1 text-[10px] text-term-faint">Pares: {peerCount} empresas del sector {sector} en el universo del scanner.</p>

                <div className="mt-3 grid gap-2">
                  {fvPE && (
                    <div className="rounded-lg border border-term-border bg-term-panel2 p-3 text-sm">
                      <div className="flex justify-between"><span>{fvPE.method}</span>
                        <b className={fvPE.upsidePct >= 0 ? "text-term-good" : "text-term-crit"}>{pct(fvPE.upsidePct)}</b></div>
                      <div className="text-xs text-term-faint">{fvPE.assumption} {fvPE.note}</div>
                    </div>
                  )}
                  {fvFcf && (
                    <div className="rounded-lg border border-term-border bg-term-panel2 p-3 text-sm">
                      <div className="flex justify-between"><span>{fvFcf.method}</span>
                        <b className={fvFcf.upsidePct >= 0 ? "text-term-good" : "text-term-crit"}>{pct(fvFcf.upsidePct)}</b></div>
                      <div className="text-xs text-term-faint">{fvFcf.assumption} {fvFcf.note}</div>
                    </div>
                  )}
                  {!fvPE && !fvFcf && <p className="text-sm text-term-muted">No calculable: faltan P/E o FCF yield de la empresa o de los pares.</p>}
                </div>

                <div className="mt-3 rounded-lg border border-term-border bg-term-panel2 p-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-term-muted">Lectura inversa — retorno requerido</span>
                    <input type="number" min={1} max={30} step={0.5} value={Math.round(reqReturn * 1000) / 10}
                      onChange={(e) => setReqReturn((Number(e.target.value) || 9) / 100)}
                      className="w-16 rounded border border-term-border bg-term-panel px-2 py-1 text-sm" />
                    <span className="text-term-faint">%</span>
                  </div>
                  <p className="mt-1 text-xs text-term-fg">
                    {impliedG !== null
                      ? `Con FCF yield ${pct(fund.fcf_yield)} y retorno requerido ${pct(reqReturn)}, el precio implica un crecimiento de FCF de ~${pct(impliedG)} (modelo Gordon, aproximación).`
                      : "No calculable: falta el FCF yield."}
                  </p>
                </div>
              </>
            )}
          </Panel>
        </>
      )}

      <Panel title="Factores del scanner (explicados)">
        {!companyScan ? (
          <p className="text-sm text-term-muted">Este instrumento no está en el último universo evaluado por el scanner.</p>
        ) : (
          <div className="grid gap-2">
            <div className="flex items-center gap-2 text-sm">
              <span className="w-24 text-term-muted">Compuesto</span>
              <span className="w-9 tabnum">{num(companyScan.composite, 0)}</span>
              <Bar v={companyScan.composite} />
            </div>
            {factors.map(([n, v]) => (
              <div key={n} className="grid gap-0.5">
                <div className="flex items-center gap-2 text-sm">
                  <span className="w-24 capitalize text-term-muted">{n.replace("_", " ")}</span>
                  <span className="w-9 tabnum">{v !== null ? num(v, 0) : "—"}</span>
                  <Bar v={v ?? 0} tone="bg-term-muted" />
                </div>
                <div className="pl-24 text-[11px] text-term-faint">{factorExplanation(n, v)}</div>
              </div>
            ))}
            <p className="text-[10px] text-term-faint">El score es atractivo relativo (percentil del universo), no una predicción de retorno.</p>
          </div>
        )}
      </Panel>

      <Panel title="Riesgos (determinísticos)">
        {risks.length === 0 ? (
          <p className="text-sm text-term-good">Sin señales de riesgo determinísticas con los datos actuales.</p>
        ) : (
          <ul className="flex flex-col gap-1 text-sm text-term-warn">
            {risks.map((r, i) => <li key={i}>• {r}</li>)}
          </ul>
        )}
      </Panel>

      <Panel title="Datos y procedencia">
        <ul className="flex flex-col gap-1 text-xs text-term-muted">
          <li>• Precio: {priceAsOf ? `al ${priceAsOf}` : "no disponible"} (Yahoo/Stooq vía el job).</li>
          <li>• Fundamentales: SEC EDGAR (último reporte anual). {missing.length ? `Faltantes: ${missing.join(", ")}.` : ""}</li>
          <li>• Scanner: {scanAsOf ? `corrida del ${scanAsOf}` : "sin fecha"} · percentiles multifactor.</li>
          <li>• Proyecciones: {preds.length ? `${preds.length} horizonte(s), emitidas ${preds[0].as_of} (origin=production, inmutable)` : "sin cobertura del modelo"}.</li>
          <li className="text-term-faint">• Modelos A/B experimentales, retorno relativo al universo; sin validación económica.</li>
        </ul>
      </Panel>
    </div>
  );
}

// Ruta con deep-link (/research/:ticker) — reutiliza la ficha.
export function CompanyFicha() {
  const { ticker } = useParams();
  return <StockFiche ticker={(ticker ?? "").toUpperCase()} />;
}

function CompRow({ label, a, b, isPct = false, suffix = "" }:
  { label: string; a: number | null; b: number | null; isPct?: boolean; suffix?: string }) {
  const fmt = (x: number | null) =>
    x === null ? "—" : isPct ? pct(x) : `${num(x, suffix === "×" ? 1 : 2)}${suffix}`;
  return (
    <tr className="border-b border-term-border last:border-0">
      <td className="py-2 text-term-muted">{label}</td>
      <td className="text-right tabnum">{fmt(a)}</td>
      <td className="text-right tabnum text-term-muted">{fmt(b)}</td>
    </tr>
  );
}
