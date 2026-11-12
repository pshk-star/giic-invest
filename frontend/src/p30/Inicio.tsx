// P3.0 Inicio — patrimonio, rentabilidad y evolución (datos reales) + la decisión del día (motor).
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useP30 } from "./P30Layout";
import { portfolioSeries, periodReturn, sparkPoints } from "./portfolio-series";
import { money, num, pct } from "../format";
import { MissingProfile } from "./MissingProfile";

const PERIODS: { k: string; m: number }[] = [{ k: "1M", m: 1 }, { k: "6M", m: 6 }, { k: "1A", m: 12 }];

export function Inicio() {
  const d = useP30();
  const nav = useNavigate();
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
  const ccy = r.currency;
  const total = d.positions.reduce((s, p) => s + (p.marketValue ?? 0), 0);
  const unreal = d.positions.reduce((s, p) => s + (p.unrealized ?? 0), 0);
  const months = PERIODS.find((p) => p.k === period)!.m;
  const ret = periodReturn(series, months);
  const vol = r.newMoney.volBefore;
  const nReduce = r.positions.filter((p) => p.action === "REDUCIR" || p.action === "VENDER").length;
  const pts = sparkPoints(series, 300, 90);
  const last = pts ? pts.trim().split(" ").pop()!.split(",") : null;

  return (
    <div>
      <div className="s-head">
        <div><div className="s-kick">Tu patrimonio · {ccy}</div><div className="s-title">Inicio</div></div>
        <span className="exp-tag">simulado</span>
      </div>

      <div className="patr">
        <div className="pt-top">
          <div>
            <div className="val">{num(total, 0)}</div>
            <div className="sub">Valor de cartera · aporte disponible {money(d.profile?.capitalAvailable ?? 0, ccy)}</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className={"ret" + (ret == null ? " na" : "")}>
              {ret == null ? "s/ datos" : `${ret >= 0 ? "▲ +" : "▼ "}${pct(ret)}`}
              <span style={{ color: "var(--muted)", fontWeight: 400 }}>· {period}</span>
            </div>
            <div className="period">
              {PERIODS.map((p) => (
                <button key={p.k} className={period === p.k ? "on" : ""} onClick={() => setPeriod(p.k)}>{p.k}</button>
              ))}
            </div>
          </div>
        </div>
        <div className="spark">
          {pts ? (
            <svg viewBox="0 0 300 90" preserveAspectRatio="none" aria-label="Evolución del patrimonio">
              <polygon fill="var(--buy-bg)" points={`${pts} 300,90 0,90`} />
              <polyline fill="none" stroke="var(--up)" strokeWidth="2" points={pts} />
              {last && <circle cx={last[0]} cy={last[1]} r="3" fill="var(--up)" />}
            </svg>
          ) : <div className="empty">Evolución no disponible: faltan precios históricos de tus posiciones.</div>}
        </div>
        {pts && <div className="sub" style={{ marginTop: 8 }}>Evolución a composición actual (tenencia de hoy × precio histórico real).</div>}
      </div>

      <div className="answer">
        <span className="lab">Decisión de hoy</span>
        <p className="lead" dangerouslySetInnerHTML={{ __html: boldMoney(r.executiveSummary) }} />
        <div className="asub">Postura: {r.posture} · topes {pct(r.constraintsUsed.maxPositionWeight)}/empresa, {pct(r.constraintsUsed.maxSectorWeight)}/sector · margen mínimo {pct(r.constraintsUsed.minMarginToBuy)}.</div>
        <div className="acts">
          <button className="btn-sm gold" onClick={() => nav("/p30/oportunidades")}>Ver oportunidades</button>
          <button className="btn-sm" onClick={() => nav("/p30/cartera")}>Ver mi cartera</button>
        </div>
      </div>

      <div className="pulse">
        <div className="m"><div className="v" style={{ color: unreal >= 0 ? "var(--up)" : "var(--reduce)" }}>{unreal >= 0 ? "+" : "−"}{num(Math.abs(unreal), 0)}</div><div className="l">Ganancia no realizada</div></div>
        <div className="m"><div className="v">{vol != null ? pct(vol) : "—"}</div><div className="l">Volatilidad anual</div></div>
        <div className="m"><div className="v" style={{ color: nReduce ? "var(--reduce)" : "var(--muted)" }}>{nReduce}</div><div className="l">A reducir</div></div>
      </div>

      <div className="note"><span className="i">◆</span><span>Una sola advertencia: recomendaciones simuladas y experimentales; montos y recortes son propuestas indicativas, no órdenes. La evolución es ilustrativa (composición actual).</span></div>
    </div>
  );
}

// resalta en oro la primera cifra monetaria del resumen del motor (sin alterar el texto)
function boldMoney(s: string): string {
  const esc = s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]!));
  return esc.replace(/(USD\s?[\d.,]+|\$[\d.,]+)/, '<b>$1</b>');
}
