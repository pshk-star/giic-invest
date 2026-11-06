import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Panel } from "../components/Panel";
import {
  getFundamentals, getInstruments, getLatestRun, getLatestScan, getPrices, getQuotes, getTransactions,
  type QuoteRow, type ScanRow,
} from "../data";
import { QuoteView } from "../components/Quote";
import { derivePositions, portfolioTotals } from "../core/portfolio-tx";
import {
  type FundamentalsPayload, type ScanFactors, factorExplanation, fairValueByFcfYield,
  fairValueByPE, impliedFcfGrowth, missingFundamentals, peerMedian, riskFlags,
} from "../core/valuation";
import { money, num, pct } from "../format";

const EMPTY_F: FundamentalsPayload = {
  pe_ttm: null, pe_forward: null, ev_ebitda: null, fcf_yield: null, roic: null, roe: null,
  rev_growth_yoy: null, eps_growth_yoy: null, net_margin: null, debt_to_equity: null, market_cap: null,
};

function Bar({ v, tone = "bg-term-accent" }: { v: number; tone?: string }) {
  return (
    <div className="h-1.5 w-full rounded bg-term-panel2">
      <div className={`h-full rounded ${tone}`} style={{ width: `${Math.max(0, Math.min(100, v))}%` }} />
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

export function CompanyFicha() {
  const { ticker: raw } = useParams();
  const ticker = (raw ?? "").toUpperCase();
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [assetClass, setAssetClass] = useState<string | null>(null);
  const [exchange, setExchange] = useState<string | null>(null);
  const [sector, setSector] = useState<string | null>(null);
  const [price, setPrice] = useState<number | null>(null);
  const [priceAsOf, setPriceAsOf] = useState<string | null>(null);
  const [quote, setQuote] = useState<QuoteRow | null>(null);
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
      const [scanAll, instMap, priceMap, quoteMap, run, txns] = await Promise.all([
        getLatestScan(), getInstruments([ticker]), getPrices([ticker]), getQuotes([ticker]),
        getLatestRun(), getTransactions(),
      ]);
      setQuote(quoteMap[ticker] ?? null);
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
        const [pr, inst] = await Promise.all([getPrices(all), getInstruments(all)]);
        const pos = derivePositions(txns, pr, inst);
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
      <Link to="/research" className="text-xs text-term-muted hover:text-term-fg">← Research</Link>

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
                  <div className="text-[10px] text-term-faint">{priceAsOf ? `cierre al ${priceAsOf}` : "sin precio aún"}</div>
                </>}
          </div>
        </div>
        {held && (
          <p className="mt-2 text-xs text-term-good">
            En tu cartera: {num(held.qty, 2)} unidades · peso {pct(held.weight)} del total.
          </p>
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
              <Metric label="P/E ttm" value={fund.pe_ttm !== null ? `${num(fund.pe_ttm, 1)}×` : "—"} />
              <Metric label="FCF yield" value={pct(fund.fcf_yield)} />
              <Metric label="ROE" value={pct(fund.roe)} />
              <Metric label="Margen neto" value={pct(fund.net_margin)} />
              <Metric label="Crec. ingresos" value={pct(fund.rev_growth_yoy)} help="interanual" />
              <Metric label="Crec. EPS" value={pct(fund.eps_growth_yoy)} help="interanual" />
              <Metric label="Deuda/Capital" value={fund.debt_to_equity !== null ? `${num(fund.debt_to_equity, 2)}×` : "—"} />
              <Metric label="Market cap" value={fund.market_cap !== null ? money(fund.market_cap) : "—"} />
            </div>
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
          <li className="text-term-faint">• Gráfico de precio histórico: llega en el próximo incremento (registro histórico point-in-time).</li>
        </ul>
      </Panel>
    </div>
  );
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
