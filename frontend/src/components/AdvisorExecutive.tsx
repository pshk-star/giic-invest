import { useState } from "react";
import { Panel } from "./Panel";
import type { Advisor2Report, Rec2, Action2, Opp2 } from "../core/advisor2";
import { money, pct } from "../format";

const ACTION: Record<Action2, { tone: string; bg: string; border: string }> = {
  COMPRAR:  { tone: "text-term-good", bg: "bg-term-good/10", border: "border-term-good/40" },
  ACUMULAR: { tone: "text-term-good", bg: "bg-term-good/10", border: "border-term-good/40" },
  MANTENER: { tone: "text-term-accent", bg: "bg-term-panel2/60", border: "border-term-border" },
  REDUCIR:  { tone: "text-term-warn", bg: "bg-term-warn/10", border: "border-term-warn/40" },
  VENDER:   { tone: "text-term-crit", bg: "bg-term-crit/10", border: "border-term-crit/40" },
  ESPERAR:  { tone: "text-term-muted", bg: "bg-term-panel2/40", border: "border-term-border" },
};
const OPP: Record<Opp2["action"], { tone: string; label: string }> = {
  COMPRAR: { tone: "text-term-good", label: "COMPRAR" },
  OBSERVAR: { tone: "text-term-info", label: "EN OBSERVACIÓN" },
  ESPERAR: { tone: "text-term-warn", label: "ESPERAR" },
  INVESTIGAR: { tone: "text-term-muted", label: "INVESTIGAR" },
};
const CONF: Record<string, string> = { alta: "text-term-good", media: "text-term-info", baja: "text-term-warn" };

function RecCard({ r }: { r: Rec2 }) {
  const [open, setOpen] = useState(false);
  const st = ACTION[r.action];
  return (
    <div className={`rounded border ${st.border} ${st.bg} p-3`}>
      <button onClick={() => setOpen(!open)} className="w-full text-left">
        <div className="flex items-center gap-2">
          <span className={`font-mono text-[11px] font-semibold px-1.5 py-[1px] rounded border ${st.border} ${st.tone}`}>{r.action}</span>
          <span className="font-mono text-sm text-term-fg">{r.ticker}</span>
          <span className={`ml-auto text-[10px] ${CONF[r.confidence]}`}>confianza {r.confidence}</span>
          <span className="text-term-faint text-[10px]">{open ? "▲" : "▼"}</span>
        </div>
        <div className="text-[12px] text-term-muted mt-1 leading-snug">{r.why}</div>
      </button>
      {open && (
        <div className="mt-2 pt-2 border-t border-term-border grid gap-1.5 text-[11px]">
          <div><span className="text-term-good">Evidencia:</span> <ul className="list-disc pl-4 text-term-muted">{r.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul></div>
          <div><span className="text-term-crit">Riesgos / qué la invalida:</span> <ul className="list-disc pl-4 text-term-muted">{r.risks.map((e, i) => <li key={i}>{e}</li>)}</ul></div>
          <div><span className="text-term-warn">Información que falta:</span> <ul className="list-disc pl-4 text-term-faint">{r.missing.map((e, i) => <li key={i}>{e}</li>)}</ul></div>
        </div>
      )}
    </div>
  );
}

export function AdvisorExecutive({ report: r }: { report: Advisor2Report }) {
  const [showRules, setShowRules] = useState(false);
  const stanceTone = r.stance === "desplegar" ? "text-term-good" : r.stance === "parcial" ? "text-term-accent" : "text-term-muted";
  return (
    <div className="flex flex-col gap-3">
      {/* Resumen del mes */}
      <Panel title="Recomendación del mes · Investment Advisor 2.0">
        <div className={`text-sm ${stanceTone} font-medium leading-snug`}>{r.monthSummary}</div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">
          <div className="rounded border border-term-border bg-term-panel2/40 p-2.5">
            <div className="text-[10px] text-term-muted">Cartera</div>
            <div className="text-base font-mono text-term-fg">{money(r.portfolioValue)}</div>
          </div>
          <div className="rounded border border-term-border bg-term-panel2/40 p-2.5">
            <div className="text-[10px] text-term-muted">Aporte a asignar</div>
            <div className="text-base font-mono text-term-fg">{money(r.cash)}</div>
          </div>
          <div className="rounded border border-term-good/40 bg-term-good/5 p-2.5">
            <div className="text-[10px] text-term-muted">A desplegar</div>
            <div className="text-base font-mono text-term-good">{money(r.invested)}</div>
          </div>
          <div className="rounded border border-term-border bg-term-panel2/40 p-2.5">
            <div className="text-[10px] text-term-muted">Mantener en liquidez</div>
            <div className="text-base font-mono text-term-fg">{money(r.cashKept)}</div>
          </div>
        </div>
      </Panel>

      {/* Propuesta de asignación */}
      <Panel title={`Propuesta de asignación del aporte (${money(r.cash)})`}>
        {r.allocation.length === 0 ? (
          <div className="text-sm text-term-muted">
            Sin asignación: ninguna posición ni candidata reúne evidencia convergente (margen de seguridad + atractivo + calidad) hoy.
            Mantener los {money(r.cash)} en liquidez es la opción consistente.
          </div>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-term-border text-left text-xs uppercase text-term-muted">
                  <th className="py-1.5">Instrumento</th><th>Tipo</th>
                  <th className="text-right">Monto</th><th className="text-right">% aporte</th>
                  <th className="text-right">Peso result.</th>
                </tr>
              </thead>
              <tbody>
                {r.allocation.map((a) => (
                  <tr key={a.ticker} className="border-b border-term-border last:border-0 align-top">
                    <td className="py-2 font-mono">{a.ticker}</td>
                    <td className="text-term-muted text-xs">{a.kind === "acumular" ? "Aumentar" : "Nueva"}</td>
                    <td className="text-right tabnum font-mono">{money(a.amount)}</td>
                    <td className="text-right tabnum">{pct(a.pctOfCash)}</td>
                    <td className="text-right tabnum text-term-muted">{pct(a.newWeight)}</td>
                  </tr>
                ))}
                <tr className="text-xs text-term-faint">
                  <td className="py-1.5" colSpan={2}>Liquidez retenida</td>
                  <td className="text-right tabnum">{money(r.cashKept)}</td>
                  <td className="text-right tabnum">{pct(r.cash > 0 ? r.cashKept / r.cash : 0)}</td>
                  <td></td>
                </tr>
              </tbody>
            </table>
            <div className="mt-2 grid gap-1">
              {r.allocation.map((a) => (
                <div key={a.ticker} className="text-[11px] text-term-faint"><b className="text-term-muted font-mono">{a.ticker}:</b> {a.reason} {a.marginLine}</div>
              ))}
            </div>
            <div className="text-[10px] text-term-faint mt-2">Suma exacta: {money(r.invested)} asignados + {money(r.cashKept)} en liquidez = {money(r.cash)}.</div>
          </>
        )}
      </Panel>

      {/* Riesgo y concentración antes/después */}
      <Panel title="Riesgo y concentración · antes → después del aporte">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="rounded border border-term-border bg-term-panel2/40 p-3">
            <div className="text-[11px] text-term-muted mb-1">Antes</div>
            <div className="font-mono text-term-fg">{r.before.effN.toFixed(1)} posiciones efectivas</div>
            <div className="text-[11px] text-term-muted mt-1">Mayor peso: {r.before.topTicker ?? "—"} {pct(r.before.topWeight)}</div>
          </div>
          <div className="rounded border border-term-accent/40 bg-term-panel2/60 p-3">
            <div className="text-[11px] text-term-muted mb-1">Después</div>
            <div className="font-mono text-term-fg">{r.after.effN.toFixed(1)} posiciones efectivas</div>
            <div className="text-[11px] text-term-muted mt-1">Mayor peso: {r.after.topTicker ?? "—"} {pct(r.after.topWeight)}</div>
          </div>
        </div>
      </Panel>

      {/* Recomendaciones por posición */}
      <Panel title="Acciones recomendadas por posición (toca para ver evidencia)">
        <div className="grid gap-2">
          {r.recommendations.map((rec) => <RecCard key={rec.ticker} r={rec} />)}
        </div>
      </Panel>

      {/* Oportunidades fuera de cartera */}
      {r.opportunities.length > 0 && (
        <Panel title="Oportunidades fuera de tu cartera">
          <div className="grid gap-1.5">
            {r.opportunities.map((o) => (
              <div key={o.ticker} className="flex items-start gap-2 text-[12px] border-b border-term-border last:border-0 pb-1.5">
                <span className={`font-mono text-[10px] font-semibold ${OPP[o.action].tone} w-28 shrink-0`}>{OPP[o.action].label}</span>
                <span className="font-mono text-term-fg w-14 shrink-0">{o.ticker}</span>
                <span className="text-term-muted">{o.note} <span className="text-term-faint">{o.marginLine}</span></span>
              </div>
            ))}
          </div>
          <div className="text-[10px] text-term-faint mt-2">Comprar una nueva aporta diversificación si su sector no está sobreexpuesto; aumentar una existente concentra. Sin Fair Value comparable ⇒ INVESTIGAR, no compra.</div>
        </Panel>
      )}

      {/* Advertencias + reglas */}
      <Panel title="Advertencias por datos incompletos y reglas de decisión"
        right={<button onClick={() => setShowRules(!showRules)} className="text-xs text-term-muted hover:text-term-fg">{showRules ? "Ocultar reglas" : "Ver reglas y pesos"}</button>}>
        <ul className="list-disc pl-4 text-[11px] text-term-warn leading-snug">
          {r.warnings.map((w, i) => <li key={i} className={w.startsWith("Fair Value V1") ? "text-term-faint" : ""}>{w}</li>)}
        </ul>
        {showRules && (
          <div className="mt-3 pt-2 border-t border-term-border">
            <ul className="list-disc pl-4 text-[11px] text-term-muted leading-snug">
              {r.rules.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
            <div className="text-[10px] text-term-faint mt-2">Datos: {r.dataUsed.join(" · ")}</div>
          </div>
        )}
      </Panel>
    </div>
  );
}
