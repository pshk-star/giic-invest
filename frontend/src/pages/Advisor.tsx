import { useEffect, useMemo, useState } from "react";
import { Panel } from "../components/Panel";
import {
  getCorporateActions, getFundamentals, getInstruments, getLatestRun, getLatestScan,
  getPriceHistory, getPrices, getSettings, getTransactions, getXrayData, saveSettings,
  type ScanRow,
} from "../data";
import { derivePositions, portfolioTotals } from "../core/portfolio-tx";
import { buildAssets, forecast, type PriceBarLite } from "../core/forecast";
import { effectiveExposure, type EtfWeight, type PortfolioHolding } from "../core/xray";
import { valuateCompany } from "../core/fundamental";
import type { FundamentalsPayload } from "../core/valuation";
import {
  reviewPositions, type PosAction, type PositionReview, type PositionReviewInput,
} from "../core/position-review";
import {
  buildAdvice, type AdvisorReport, type Decision, type Holding, type Recommendation,
  type RiskModel, type ScanInfo,
} from "../core/advisor";
import { money, num, pct } from "../format";

const ACTION_STYLE: Record<Decision["action"], { label: string; tone: string }> = {
  COMPRAR: { label: "COMPRAR", tone: "text-term-good" },
  AUMENTAR: { label: "AUMENTAR", tone: "text-term-good" },
  MANTENER: { label: "MANTENER", tone: "text-term-accent" },
  REDUCIR: { label: "REDUCIR", tone: "text-term-warn" },
  VENDER: { label: "VENDER", tone: "text-term-crit" },
  NO_HACER_NADA: { label: "NO HACER NADA", tone: "text-term-muted" },
};

const POS_STYLE: Record<PosAction, { tone: string; bg: string }> = {
  AUMENTAR: { tone: "text-term-good", bg: "bg-term-good/10" },
  MANTENER: { tone: "text-term-accent", bg: "bg-term-panel" },
  REDUCIR: { tone: "text-term-warn", bg: "bg-term-warn/10" },
  VENDER: { tone: "text-term-crit", bg: "bg-term-crit/10" },
  REVISAR: { tone: "text-term-muted", bg: "bg-term-panel" },
};

const COMMODITY_T = ["GLD", "SLV", "IAU", "PPLT", "PALL", "SGOL", "SIVR"];
function classifyKind(ticker: string, assetClass: string | null): "equity" | "etf" | "commodity" {
  const ac = (assetClass ?? "").toLowerCase();
  if (COMMODITY_T.includes(ticker.toUpperCase()) || ac === "commodity") return "commodity";
  if (ac === "etf" || ac === "fund" || ac === "etn" || ac === "mutualfund") return "etf";
  return "equity";
}

type RawPos = Omit<PositionReviewInput, "riskPct" | "valuation" | "totalValue" | "maxWeightAsset" | "maxWeightSector">;

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
  const [risk, setRisk] = useState<RiskModel | undefined>();
  const [fundamentals, setFundamentals] = useState<Record<string, FundamentalsPayload>>({});
  const [posRaw, setPosRaw] = useState<RawPos[]>([]);
  const [totalValue, setTotalValue] = useState(0);

  useEffect(() => {
    (async () => {
      const txns = await getTransactions();
      const tickers = Array.from(new Set(txns.map((t) => t.ticker.toUpperCase())));
      const [prices, instruments, rows, run, settings, ca, funds] = await Promise.all([
        getPrices(tickers), getInstruments(tickers), getLatestScan(), getLatestRun(), getSettings(),
        getCorporateActions(tickers), getFundamentals(tickers),
      ]);
      const pos = derivePositions(txns, prices, instruments, ca);
      const totals = portfolioTotals(pos);
      const held = pos.filter((p) => p.qty > 1e-9);
      const hs: Holding[] = held.map((p) => ({
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
      setFundamentals(funds);
      if (settings) {
        setCash(settings.capital_available || 3000);
        setMaxAsset(settings.max_weight_per_asset || 0.25);
        setMaxSector(settings.max_weight_per_sector || 0.40);
      }
      setLoaded(true);

      // Exposición efectiva (look-through de ETFs vía X-Ray) para la revisión por posición.
      const pricedAll = held.filter((p) => p.marketValue != null && p.marketValue > 0);
      const total = pricedAll.reduce((s, p) => s + (p.marketValue ?? 0), 0);
      setTotalValue(total);
      const phold: PortfolioHolding[] = pricedAll.map((p) => ({
        ticker: p.ticker, isEtf: classifyKind(p.ticker, instruments[p.ticker]?.asset_class ?? p.asset_class ?? null) !== "equity",
        valueUsd: p.marketValue ?? 0,
      }));
      const etfs = phold.filter((h) => h.isEtf).map((h) => h.ticker);
      let effByTicker = new Map<string, number>();     // exposición efectiva USD por empresa
      let effBySector = new Map<string, number>();
      let xrayTotal = total;
      try {
        const xd = etfs.length ? await getXrayData(etfs) : { weights: [] };
        const ew: EtfWeight[] = (xd.weights ?? []).filter((w) => w.weight != null && w.ticker).map((w) => ({
          etf: w.etf, ticker: w.ticker as string, weight: w.weight as number,
          name: w.name ?? undefined, assetClass: w.asset_class, sector: w.sector ?? undefined,
        }));
        const xr = effectiveExposure(phold, ew);
        xrayTotal = xr.totalUsd || total;
        for (const c of xr.byCompany) {
          effByTicker.set(c.ticker.toUpperCase(), c.total);
          const sec = c.sector || "Sin clasificar";
          effBySector.set(sec, (effBySector.get(sec) ?? 0) + c.total);
        }
      } catch { /* sin X-Ray, exposición efectiva = directa */ }

      setPosRaw(pricedAll.map((p) => {
        const kind = classifyKind(p.ticker, instruments[p.ticker]?.asset_class ?? p.asset_class ?? null);
        const sector = instruments[p.ticker]?.sector ?? null;
        const mv = p.marketValue ?? 0;
        const directW = total > 0 ? mv / total : 0;
        const effUsd = effByTicker.get(p.ticker.toUpperCase());
        const effW = kind === "equity" && effUsd != null && xrayTotal > 0 ? effUsd / xrayTotal : (kind === "equity" ? directW : directW);
        const secUsd = sector ? effBySector.get(sector) : undefined;
        return {
          ticker: p.ticker, name: p.name, sector, kind,
          price: p.price, priceAsOf: p.priceAsOf, marketValue: mv,
          weight: directW,
          effectiveWeight: kind === "equity" ? effW : directW,
          sectorWeight: secUsd != null && xrayTotal > 0 ? secUsd / xrayTotal : null,
        };
      }));

      // Modelo de riesgo (covarianzas) desde el motor de Proyección — alimenta las decisiones.
      const priced = held.filter((p) => p.marketValue != null && p.marketValue > 0);
      if (priced.length) {
        const hist: Record<string, PriceBarLite[]> = {};
        await Promise.all(priced.map(async (p) => { hist[p.ticker] = await getPriceHistory(p.ticker); }));
        const valueMap = Object.fromEntries(priced.map((p) => [p.ticker, p.marketValue ?? 0]));
        const assets = buildAssets(hist, valueMap);
        if (assets.length) {
          const f = forecast(assets, { drift: "neutral" });
          const h12 = f.horizons.find((x) => x.days === 252);
          setRisk({
            annVol: f.annVol, effectiveN: f.effectiveN, hhi: f.hhi,
            probLoss12m: h12?.probLoss ?? 0,
            contrib: f.riskContrib.map((c) => ({ ticker: c.ticker, weightPct: c.weightPct, riskPct: c.riskPct })),
          });
        }
      }
    })().catch((e) => setErr(String(e)));
  }, []);

  const report: AdvisorReport = useMemo(
    () => buildAdvice(holdings, scan, cash, { maxWeightAsset: maxAsset, maxWeightSector: maxSector }, scanAsOf, risk),
    [holdings, scan, cash, maxAsset, maxSector, scanAsOf, risk]
  );

  const positionReviews = useMemo<PositionReview[]>(() => {
    if (!posRaw.length) return [];
    const riskBy = new Map((risk?.contrib ?? []).map((c) => [c.ticker.toUpperCase(), c.riskPct]));
    const inputs: PositionReviewInput[] = posRaw.map((p) => ({
      ...p,
      riskPct: riskBy.get(p.ticker.toUpperCase()) ?? null,
      valuation: p.kind === "equity"
        ? valuateCompany({ ticker: p.ticker, name: p.name, sector: p.sector, price: p.price, priceAsOf: p.priceAsOf, f: fundamentals[p.ticker.toUpperCase()] ?? fundamentals[p.ticker] })
        : null,
      totalValue, maxWeightAsset: maxAsset, maxWeightSector: maxSector,
    }));
    return reviewPositions(inputs);
  }, [posRaw, fundamentals, totalValue, risk, maxAsset, maxSector]);

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
          {/* 1) PRIMERO: qué hacer con la cartera actual */}
          <Panel title="¿Qué haría hoy con mi cartera actual?"
            right={<span className="text-xs text-term-faint">{positionReviews.length} posición(es)</span>}>
            <p className="mb-2 text-sm text-term-muted">
              Reviso <b>cada posición</b> integrando valoración fundamental (preliminar), exposición
              efectiva vía ETFs, contribución al riesgo y calidad de datos. No recorto/vendo por
              concentración sola ni compro por score; sin evidencia suficiente → <b>MANTENER</b> o <b>REVISAR</b>.
            </p>
            {positionReviews.length === 0 ? (
              <p className="text-sm text-term-faint">Calculando revisión por posición… (requiere precios e historial).</p>
            ) : (
              <>
                <div className="grid gap-2">
                  {positionReviews.slice(0, 5).map((r) => <PositionCard key={r.ticker} r={r} />)}
                </div>
                <div className="mt-3 overflow-x-auto">
                  <div className="mb-1 text-xs uppercase tracking-wide text-term-faint">Todas tus posiciones</div>
                  <table className="w-full min-w-[640px] text-sm">
                    <thead>
                      <tr className="border-b border-term-border text-left text-xs uppercase text-term-muted">
                        <th className="py-1.5">#</th><th>Posición</th><th>Acción</th>
                        <th className="text-right">Peso directo</th><th className="text-right">Exp. efectiva</th>
                        <th className="text-right">Valor central</th><th className="text-right">Calidad</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positionReviews.map((r) => {
                        const c = r.scenarios?.find((s) => s.key === "central");
                        return (
                          <tr key={r.ticker} className="border-b border-term-border last:border-0">
                            <td className="py-1.5 tabnum text-term-faint">{r.priority}</td>
                            <td className="font-mono font-semibold">{r.ticker}</td>
                            <td><span className={`text-xs font-bold ${POS_STYLE[r.action].tone}`}>{r.action}</span></td>
                            <td className="text-right tabnum">{pct(r.weight)}</td>
                            <td className="text-right tabnum">{r.effectiveWeight != null ? pct(r.effectiveWeight) : "—"}</td>
                            <td className={`text-right tabnum ${c ? (c.upside >= 0 ? "text-term-good" : "text-term-crit") : "text-term-faint"}`}>{c ? `${c.upside >= 0 ? "+" : ""}${pct(c.upside)}` : "—"}</td>
                            <td className="text-right text-xs text-term-muted">{r.kind === "equity" ? r.evidenceQuality : r.kind}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </Panel>

          {/* 2) Decisiones priorizadas (cartera + oportunidades) — entregable central */}
          <Panel title="Tus decisiones de hoy (priorizadas)"
            right={<span className="text-xs text-term-faint">{report.decisions.length} decisión(es)</span>}>
            <p className="mb-3 text-sm text-term-muted">
              Qué haría yo primero con tu cartera, en orden de importancia. Cada decisión es
              explicable y sale de tus datos reales — no de un pronóstico.
            </p>
            {risk && (
              <div className="mb-3 flex flex-wrap gap-4 rounded-lg border border-term-border bg-term-panel2 px-3 py-2 text-xs text-term-muted">
                <span>Volatilidad anual <b className="text-term-fg tabnum">{(risk.annVol * 100).toFixed(1)}%</b></span>
                <span>Concentración efectiva <b className="text-term-fg tabnum">{risk.effectiveN.toFixed(1)}</b> posiciones</span>
                <span>Prob. de pérdida a 12m <b className="text-term-fg tabnum">{(risk.probLoss12m * 100).toFixed(0)}%</b></span>
                <span className="text-term-faint">(modelo de riesgo por covarianzas, histórico ajustado)</span>
              </div>
            )}
            <div className="grid gap-2">
              {report.decisions.map((d) => <DecisionCard key={d.id} d={d} />)}
            </div>
          </Panel>

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

function PositionCard({ r }: { r: PositionReview }) {
  const [open, setOpen] = useState(r.priority <= 3 && r.action !== "MANTENER");
  const st = POS_STYLE[r.action];
  const evTone = r.evidenceQuality === "alta" ? "text-term-good" : r.evidenceQuality === "baja" ? "text-term-crit" : "text-term-muted";
  return (
    <div className={`rounded-lg border border-term-border p-3 ${st.bg}`}>
      <button onClick={() => setOpen(!open)} className="flex w-full items-start justify-between gap-2 text-left">
        <span className="flex items-start gap-2">
          <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded bg-term-panel2 text-[11px] font-semibold text-term-faint tabnum">{r.priority}</span>
          <span className="text-sm">
            <span className={`font-mono text-xs font-bold ${st.tone}`}>{r.action}</span>
            <span className="ml-1 font-mono font-semibold text-term-fg">{r.ticker}</span>
            {r.name && <span className="text-term-muted"> · {r.name}</span>}
            <span className="ml-2 text-xs text-term-faint">{r.price != null ? `${money(r.price)}` : ""}{r.priceAsOf ? ` · ${r.priceAsOf}` : ""}</span>
          </span>
        </span>
        <span className="shrink-0 text-xs text-term-faint">{open ? "▲" : "▼"}</span>
      </button>
      <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 pl-7 text-xs text-term-muted">
        <span>Peso directo <b className="text-term-fg">{pct(r.weight)}</b></span>
        {r.effectiveWeight != null && <span>Exp. efectiva <b className="text-term-fg">{pct(r.effectiveWeight)}</b></span>}
        {r.targetWeight != null && <span>Objetivo <b className="text-term-fg">{pct(r.targetWeight)}</b></span>}
        {r.amountUsd != null && r.amountUsd !== 0 && <span>Monto <b className={r.amountUsd < 0 ? "text-term-warn" : "text-term-good"}>{r.amountUsd < 0 ? "−" : "+"}{money(Math.abs(r.amountUsd))}</b></span>}
        <span>Evidencia <b className={evTone}>{r.evidenceQuality}</b></span>
      </div>
      <p className="mt-1 pl-7 text-xs text-term-fg">{r.valuationLine}</p>
      {r.beforeAfter && <p className="pl-7 text-xs text-term-accent">{r.beforeAfter}</p>}
      {open && (
        <div className="mt-2 grid gap-2 pl-7 text-xs">
          {r.scenarios && r.scenarios.length > 0 && (
            <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-term-muted">
              {r.scenarios.map((s) => <span key={s.key}>{s.label}: <b className="text-term-fg">{money(s.fairValue)}</b> ({s.upside >= 0 ? "+" : ""}{pct(s.upside)})</span>)}
            </div>
          )}
          <Block title="Por qué" items={r.rationale} tone="text-term-fg" />
          <Block title="Riesgos" items={r.risks} tone="text-term-muted" />
          <Block title="Qué invalidaría la tesis" items={r.whatInvalidates} tone="text-term-muted" />
        </div>
      )}
    </div>
  );
}

function DecisionCard({ d }: { d: Decision }) {
  const [open, setOpen] = useState(d.priority <= 2);
  const st = ACTION_STYLE[d.action];
  const conf = d.confidence === "alta" ? "text-term-good" : d.confidence === "baja" ? "text-term-crit" : "text-term-muted";
  return (
    <div className="rounded-lg border border-term-border bg-term-panel2 p-3">
      <button onClick={() => setOpen(!open)} className="flex w-full items-start justify-between gap-2 text-left">
        <span className="flex items-start gap-2">
          <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded bg-term-panel text-[11px] font-semibold text-term-faint tabnum">{d.priority}</span>
          <span className="text-sm">
            <span className={`font-mono text-xs font-bold ${st.tone}`}>{st.label}</span>
            {d.ticker && <span className="ml-1 font-mono font-semibold text-term-fg">{d.ticker}</span>}
            <span className="text-term-fg"> — {d.headline}</span>
          </span>
        </span>
        <span className="shrink-0 text-xs text-term-faint">{open ? "▲" : "▼"}</span>
      </button>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 pl-7 text-xs text-term-muted">
        <span>Ahora: <b className="text-term-fg">{d.metricNow}</b></span>
        <span>Referencia: {d.reference}</span>
        {d.suggestedDeltaUsd != null && (
          <span>Sugerido: <b className={d.suggestedDeltaUsd < 0 ? "text-term-warn" : "text-term-good"}>{d.suggestedDeltaUsd < 0 ? "−" : "+"}{money(Math.abs(d.suggestedDeltaUsd))}</b>{d.suggestedTargetWeight != null && <> → {pct(d.suggestedTargetWeight)}</>}</span>
        )}
        <span>Confianza: <b className={conf}>{d.confidence}</b></span>
      </div>
      <p className="mt-1.5 pl-7 text-xs text-term-accent">{d.expectedImpact}</p>
      {open && (
        <div className="mt-2 grid gap-2 pl-7 text-xs">
          <Block title="Por qué" items={d.rationale} tone="text-term-fg" />
          <Block title="Qué cambiaría la decisión" items={d.whatWouldChange} tone="text-term-muted" />
          <Block title="Datos usados" items={d.dataSources} tone="text-term-muted" />
          <Block title="Limitaciones" items={d.limitations} tone="text-term-faint" />
        </div>
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
