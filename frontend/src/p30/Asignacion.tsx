// P3.0 Asignación interactiva — varía el aporte y recomputa con el MOTOR real (buildUnifiedAdvisor),
// no con una fórmula propia. Muestra el reparto, el impacto en riesgo y los escenarios que el planner ya
// considera (elegido vs alternativas). Experimental y NO ejecutable: nada se ejecuta; se registra para
// evaluarlo después (P2.6). No es una pantalla principal: sub-flujo accesible desde Inicio.
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useP30 } from "./P30Layout";
import { MissingProfile } from "./MissingProfile";
import { buildUnifiedAdvisor } from "../core/advisor-engine";
import { investableAmount } from "../core/advisor-profile";
import { num, pct } from "../format";

const SCEN_LABEL: Record<string, string> = { completa: "Desplegar", parcial: "Parcial", efectivo: "Conservar efectivo", valor: "Por valor", diversificar: "Diversificar", etf: "Diversificar (ETF)" };

export function Asignacion() {
  const d = useP30();
  const nav = useNavigate();
  const base = d.profile ? investableAmount(d.profile) || d.profile.monthlyContribution || 3000 : 3000;
  const [amt, setAmt] = useState<number>(Math.round(base));

  const rep = useMemo(() => {
    if (!d.profile || !d.scanInput) return null;
    return buildUnifiedAdvisor({ profile: { ...d.profile, monthlyContribution: amt }, scanInput: d.scanInput, etfInfo: d.etfInfo });
  }, [amt, d.profile, d.scanInput, d.etfInfo]);

  if (d.loading) return <div className="state">Calculando…</div>;
  if (d.missing) return <MissingProfile missing={d.missing} />;
  if (d.err) return <div className="state err">No se pudieron cargar los datos: {d.err}</div>;
  if (!rep) return <div className="state">Sin datos.</div>;

  const nm = rep.newMoney;
  const ccy = rep.currency;
  const deployed = nm.legs.reduce((s, l) => s + l.amount, 0);
  const dVol = nm.volAfter - nm.volBefore;

  return (
    <div>
      <button className="ficha-back" onClick={() => nav("/p30")}>‹ Volver a Inicio</button>
      <div className="s-head">
        <div><div className="s-kick">Reparto del aporte · recomputado por el motor</div><div className="s-title">Asignar mi aporte</div></div>
        <span className="exp-tag">experimental · no ejecutable</span>
      </div>

      <div className="alloc">
        <div className="ah"><div><div style={{ fontSize: 12, color: "var(--muted)" }}>Aporte a repartir</div><div className="amt">{num(amt, 0)} {ccy}</div></div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>postura: <b style={{ color: "var(--gold)" }}>{nm.chosen in SCEN_LABEL ? SCEN_LABEL[nm.chosen] : nm.chosen}</b></div>
        </div>
        <div className="ctrl">
          <label><span>Monto del aporte</span><span>{num(amt, 0)} {ccy}</span></label>
          <input type="range" min={500} max={Math.max(6000, base * 2)} step={250} value={amt} onChange={(e) => setAmt(Number(e.target.value))} aria-label="Monto del aporte" />
        </div>

        <div className="seg-split">
          {nm.legs.map((l, i) => <i key={l.ticker} style={{ width: `${(l.amount / amt) * 100}%`, background: "var(--buy)", opacity: 1 - i * 0.12 }} />)}
          {amt - deployed > 0 && <i style={{ width: `${((amt - deployed) / amt) * 100}%`, background: "var(--line2)" }} />}
        </div>

        <div className="legs">
          {nm.legs.length === 0 && <div style={{ fontSize: 12.5, color: "var(--muted)" }}>Ninguna compra supera el umbral de margen+confianza: conservar efectivo es la respuesta.</div>}
          {nm.legs.map((l) => (
            <div className="leg" key={l.ticker}><span className="tk" style={{ color: "var(--buy)" }}>{l.ticker}</span> {l.reason} <span className="amt2">{num(l.amount, 0)}</span></div>
          ))}
          {amt - deployed > 0 && <div className="leg"><span className="tk" style={{ color: "var(--muted)" }}>Efectivo</span> disciplina de liquidez <span className="amt2" style={{ color: "var(--muted)" }}>{num(amt - deployed, 0)}</span></div>}
        </div>

        <div className="impact">
          <div className="m"><div className="l">Desplegado</div><div className="v">{num(deployed, 0)}</div></div>
          <div className="m"><div className="l">Efectivo</div><div className="v">{num(amt - deployed, 0)}</div></div>
          <div className="m"><div className="l">Riesgo (vol)</div><div className="v">{pct(nm.volAfter)} <small style={{ color: dVol <= 0 ? "var(--up)" : "var(--reduce)" }}>{dVol >= 0 ? "+" : ""}{(dVol * 100).toFixed(1)}pp</small></div></div>
        </div>

        {nm.alternatives.length > 0 && (
          <div className="block"><h5>Escenarios considerados</h5>
            <div className="scen-cmp">
              <div className="sc on"><b>{nm.chosen in SCEN_LABEL ? SCEN_LABEL[nm.chosen] : nm.chosen}</b><span>elegido · desplegado {num(deployed, 0)} · efectivo {num(amt - deployed, 0)}</span></div>
              {nm.alternatives.map((a) => (
                <div className="sc" key={a.id}><b>{a.id in SCEN_LABEL ? SCEN_LABEL[a.id] : a.id}</b><span>desplegado {num(a.deployed, 0)} · efectivo {num(a.cashKept, 0)} · score {a.score}</span></div>
              ))}
            </div>
          </div>
        )}

        <button className="btn-sm gold" style={{ marginTop: 14 }}>Registrar decisión</button>
        <div className="note"><span className="i">◆</span><span>Montos condicionados por límites y heurísticas: propuesta experimental, no asignación óptima. Comparar escenarios no predice retornos. Nada se ejecuta — se registraría para evaluarlo después, sin look-ahead.</span></div>
      </div>
    </div>
  );
}
