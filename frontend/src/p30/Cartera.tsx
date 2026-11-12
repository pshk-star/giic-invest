// P3.0 Mi cartera — gráficos informativos (no decorativos) sobre datos reales: evolución (comp. actual),
// composición, exposición REAL mirando dentro de los ETF, y concentración. Reutiliza posiciones, etfInfo
// (X-ray) y el riesgo del motor; no calcula valoraciones ni recomendaciones aquí.
import { useMemo, useState } from "react";
import { useP30 } from "./P30Layout";
import { MissingProfile } from "./MissingProfile";
import { portfolioSeries, periodReturn, sparkPoints } from "./portfolio-series";
import { num, pct } from "../format";

const ETF = ["etf", "fund", "etn", "mutualfund"];
const isEtf = (ac?: string | null) => ETF.includes((ac ?? "").toLowerCase());
const PERIODS = [{ k: "1M", m: 1 }, { k: "6M", m: 6 }, { k: "1A", m: 12 }];

export function Cartera() {
  const d = useP30();
  const [period, setPeriod] = useState("1A");
  const series = useMemo(
    () => portfolioSeries(d.positions.map((p) => ({ ticker: p.ticker, qty: p.qty })), d.priceHistory),
    [d.positions, d.priceHistory],
  );

  if (d.loading) return <div className="state">Calculando…</div>;
  if (d.missing) return <MissingProfile missing={d.missing} />;
  if (d.err) return <div className="state err">No se pudieron cargar los datos: {d.err}</div>;
  if (!d.report) return <div className="state">Sin datos.</div>;

  const r = d.report;
  const total = d.positions.reduce((s, p) => s + (p.marketValue ?? 0), 0);
  const pos = d.positions.map((p) => ({
    ticker: p.ticker, w: total > 0 ? (p.marketValue ?? 0) / total : 0, etf: isEtf(p.asset_class),
  })).sort((a, b) => b.w - a.w);

  // Exposición real: mira dentro de los ETF (equity_pct). RV = directas (acciones) + parte equity de ETF.
  let equity = 0, nonEquity = 0, etfW = 0, directW = 0;
  for (const p of pos) {
    if (p.etf) {
      etfW += p.w;
      const info = d.etfInfo[p.ticker];
      const eq = info?.equityPct != null ? info.equityPct : (info?.role === "commodity" ? 0 : 1);
      equity += p.w * eq; nonEquity += p.w * (1 - eq);
    } else { directW += p.w; equity += p.w; }   // posiciones directas = acciones (renta variable)
  }

  const months = PERIODS.find((p) => p.k === period)!.m;
  const ret = periodReturn(series, months);
  const pts = sparkPoints(series, 300, 90);
  const last = pts ? pts.trim().split(" ").pop()!.split(",") : null;
  const top = pos.slice(0, 6);
  const rest = pos.slice(6).reduce((s, p) => s + p.w, 0);
  const vol = r.newMoney.volBefore;
  const concHigh = r.risks.some((x) => /concentraci[oó]n elevada|por encima del l[ií]mite/i.test(x)) || (top[0]?.w ?? 0) > r.constraintsUsed.maxPositionWeight || etfW > r.constraintsUsed.maxSectorWeight;
  const barColor = (p: { etf: boolean; ticker: string }) =>
    !p.etf ? "var(--gold)" : d.etfInfo[p.ticker]?.role === "commodity" ? "var(--metal)" : "var(--research)";

  return (
    <div>
      <div className="s-head"><div><div className="s-kick">{d.positions.length} posiciones · {num(total, 0)} {r.currency}</div><div className="s-title">Mi cartera</div></div></div>

      <div className="kpi">
        <div className="m"><div className="v" style={{ color: ret == null ? "var(--muted)" : ret >= 0 ? "var(--up)" : "var(--reduce)" }}>{ret == null ? "—" : (ret >= 0 ? "+" : "") + pct(ret)}</div><div className="l">Variación {period} · comp. actual</div></div>
        <div className="m"><div className="v">{vol != null ? pct(vol) : "—"}</div><div className="l">Volatilidad anual</div></div>
        <div className="m"><div className="v">{pct(equity)}</div><div className="l">Renta variable real</div></div>
        <div className="m"><div className="v">{pct(etfW)}</div><div className="l">En vehículos (ETF)</div></div>
      </div>

      <div className="charts">
        <div className="chart">
          <h6>Evolución del patrimonio</h6>
          <p className="cap">Composición actual × precio histórico · no es tu rentabilidad real</p>
          <div className="period" style={{ marginBottom: 8 }}>
            {PERIODS.map((p) => <button key={p.k} className={period === p.k ? "on" : ""} onClick={() => setPeriod(p.k)}>{p.k}</button>)}
          </div>
          {pts ? (
            <svg viewBox="0 0 300 90" preserveAspectRatio="none" aria-label="Evolución">
              <polygon fill="var(--buy-bg)" points={`${pts} 300,90 0,90`} />
              <polyline fill="none" stroke="var(--up)" strokeWidth="2" points={pts} />
              {last && <circle cx={last[0]} cy={last[1]} r="3" fill="var(--up)" />}
            </svg>
          ) : <div className="empty">Faltan precios históricos.</div>}
        </div>

        <div className="chart">
          <h6>Composición</h6><p className="cap">Peso por posición · % de cartera</p>
          {top.map((p) => (
            <div className="comp-row" key={p.ticker}>
              <span className="cl">{p.ticker}</span>
              <span className="cb"><i style={{ width: `${Math.min(100, p.w / (top[0].w || 1) * 100)}%`, background: barColor(p) }} /></span>
              <span className="cv">{pct(p.w)}</span>
            </div>
          ))}
          {rest > 0 && <div className="comp-row"><span className="cl">resto</span><span className="cb"><i style={{ width: `${Math.min(100, rest / (top[0].w || 1) * 100)}%`, background: "var(--line2)" }} /></span><span className="cv">{pct(rest)}</span></div>}
        </div>

        <div className="chart">
          <h6>Exposición real vs aparente</h6><p className="cap">Lo que esconden los ETF (look-through)</p>
          <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 3 }}>Aparente (por vehículo)</div>
          <div className="exp-bar">
            <i style={{ width: `${directW * 100}%`, background: "var(--hold)" }}>{directW >= 0.12 ? `Acciones ${pct(directW, 0)}` : ""}</i>
            <i style={{ width: `${etfW * 100}%`, background: "var(--line2)", color: "var(--fg)" }}>{etfW >= 0.12 ? `ETF ${pct(etfW, 0)}` : ""}</i>
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", margin: "6px 0 3px" }}>Real (mirando dentro)</div>
          <div className="exp-bar">
            <i style={{ width: `${equity * 100}%`, background: "var(--research)" }}>{equity >= 0.12 ? `Renta variable ${pct(equity, 0)}` : ""}</i>
            <i style={{ width: `${nonEquity * 100}%`, background: "var(--metal)" }}>{nonEquity >= 0.1 ? pct(nonEquity, 0) : ""}</i>
          </div>
          <div className="legend"><span><i style={{ background: "var(--research)" }} />Renta variable</span><span><i style={{ background: "var(--metal)" }} />Metales / commodity</span></div>
          {Math.abs(equity - directW) > 0.08 && <div className="flag gold">Tu cartera no es {pct(directW, 0)}/{pct(etfW, 0)}: al mirar dentro de los ETF, la renta variable real es {pct(equity, 0)}.</div>}
        </div>

        <div className="chart">
          <h6>Concentración</h6><p className="cap">Posición mayor y vehículos · límite {pct(r.constraintsUsed.maxSectorWeight, 0)}/sector</p>
          <div className="comp-row"><span className="cl" style={{ width: 90 }}>Mayor ({top[0]?.ticker})</span><span className="cb"><i style={{ width: `${Math.min(100, top[0] ? top[0].w / r.constraintsUsed.maxPositionWeight * 100 : 0)}%`, background: top[0] && top[0].w > r.constraintsUsed.maxPositionWeight ? "var(--reduce)" : "var(--gold)" }} /></span><span className="cv">{top[0] ? pct(top[0].w) : "—"}</span></div>
          <div className="comp-row"><span className="cl" style={{ width: 90 }}>Vehículos (ETF)</span><span className="cb"><i style={{ width: `${Math.min(100, etfW / r.constraintsUsed.maxSectorWeight * 100)}%`, background: etfW > r.constraintsUsed.maxSectorWeight ? "var(--reduce)" : "var(--research)" }} /></span><span className="cv">{pct(etfW)}</span></div>
          <div className="kv" style={{ marginTop: 8 }}><span>HHI sector (motor)</span><b>{hhiFromRisks(r.risks)}</b></div>
          {concHigh && <div className="flag">Hay un nombre o grupo por encima del límite: revisa la concentración.</div>}
        </div>
      </div>

      <div className="note"><span className="i">◆</span><span>Gráficos sobre datos reales (posiciones y look-through de X-ray). La evolución es a composición actual, no tu rentabilidad real. Los recortes propuestos (en Oportunidades/decisión) son escenarios indicativos.</span></div>
    </div>
  );
}

// extrae "HHI sector 0.341" del texto de riesgos del motor (sin recalcular)
function hhiFromRisks(risks: string[]): string {
  for (const r of risks) { const m = r.match(/HHI sector ([\d.]+)/i); if (m) return m[1]; }
  return "—";
}
