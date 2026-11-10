import { useState } from "react";
import { Panel } from "./Panel";
import type { Advisor2Report, Rec2, Opp2, RouteEval, PositionAction, ContribAction } from "../core/advisor2";
import { money, pct } from "../format";

const POS: Record<PositionAction, { tone: string; border: string }> = {
  MANTENER: { tone: "text-term-accent", border: "border-term-border" },
  REDUCIR:  { tone: "text-term-warn", border: "border-term-warn/40" },
  VENDER:   { tone: "text-term-crit", border: "border-term-crit/40" },
  REVISAR:  { tone: "text-term-info", border: "border-term-info/40" },
};
const CONTRIB: Record<ContribAction, { tone: string }> = {
  ACUMULAR: { tone: "text-term-good" }, COMPRAR: { tone: "text-term-good" }, ESPERAR: { tone: "text-term-muted" },
};
const CARD_BG: Record<PositionAction, string> = {
  MANTENER: "bg-term-panel2/50 border-term-border", REDUCIR: "bg-term-warn/8 border-term-warn/40",
  VENDER: "bg-term-crit/8 border-term-crit/40", REVISAR: "bg-term-info/8 border-term-info/40",
};
const OPP: Record<Opp2["action"], { tone: string; label: string }> = {
  COMPRAR: { tone: "text-term-good", label: "COMPRAR" },
  OBSERVAR: { tone: "text-term-info", label: "EN OBSERVACIÓN" },
  ESPERAR: { tone: "text-term-warn", label: "ESPERAR" },
  INVESTIGAR: { tone: "text-term-muted", label: "INVESTIGAR" },
};
const CONF: Record<string, string> = { alta: "text-term-good", media: "text-term-info", baja: "text-term-warn" };
const TIER: Record<string, string> = { confiable: "FV confiable", preliminar: "FV preliminar", vehiculo: "Vehículo", "sin-datos": "Sin FV" };
const ROUTE_NAME: Record<RouteEval["id"], string> = { A: "A · Aumentar existentes", B: "B · Oportunidades nuevas", C: "C · ETF diversificado", D: "D · Liquidez" };

function RecCard({ r }: { r: Rec2 }) {
  const [open, setOpen] = useState(false);
  const ps = POS[r.positionAction]; const cs = CONTRIB[r.contribAction];
  const contribLabel = r.contribAction === "ACUMULAR" && r.contribAmount != null ? `ACUMULAR ${money(r.contribAmount)}` : r.contribAction;
  return (
    <div className={`rounded border p-3 ${CARD_BG[r.positionAction]}`}>
      <button onClick={() => setOpen(!open)} className="w-full text-left">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-sm text-term-fg">{r.ticker}</span>
          <span className="text-[9px] text-term-faint border border-term-border rounded px-1">{TIER[r.tier]}</span>
          <span className={`ml-auto text-[10px] ${CONF[r.confidence]}`}>confianza {r.confidence}</span>
          <span className="text-term-faint text-[10px]">{open ? "▲" : "▼"}</span>
        </div>
        <div className="grid sm:grid-cols-2 gap-1.5 mt-2">
          <div className="rounded border border-term-border/60 bg-term-bg/30 p-1.5">
            <div className="text-[9px] text-term-faint uppercase tracking-wide">Posición existente</div>
            <div className={`font-mono text-[12px] font-semibold ${ps.tone}`}>{r.positionAction}</div>
            <div className="text-[11px] text-term-muted leading-snug mt-0.5">{r.positionWhy}</div>
          </div>
          <div className="rounded border border-term-border/60 bg-term-bg/30 p-1.5">
            <div className="text-[9px] text-term-faint uppercase tracking-wide">Aporte nuevo</div>
            <div className={`font-mono text-[12px] font-semibold ${cs.tone}`}>{contribLabel}</div>
            <div className="text-[11px] text-term-muted leading-snug mt-0.5">{r.contribWhy}</div>
          </div>
        </div>
        {(r.favor.length > 0 || r.penalize.length > 0) && (
          <div className="flex flex-wrap gap-1.5 mt-1.5">
            {r.favor.map((f, i) => <span key={`f${i}`} className="text-[10px] text-term-good border border-term-good/30 rounded px-1.5 py-[1px]">+ {f}</span>)}
            {r.penalize.map((p, i) => <span key={`p${i}`} className="text-[10px] text-term-warn border border-term-warn/30 rounded px-1.5 py-[1px]">− {p}</span>)}
          </div>
        )}
      </button>
      {open && (
        <div className="mt-2 pt-2 border-t border-term-border grid gap-1.5 text-[11px]">
          <div><span className="text-term-good">Evidencia:</span><ul className="list-disc pl-4 text-term-muted">{r.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul></div>
          <div><span className="text-term-crit">Riesgos / qué la invalida:</span><ul className="list-disc pl-4 text-term-muted">{r.risks.map((e, i) => <li key={i}>{e}</li>)}</ul></div>
          <div><span className="text-term-warn">Información que falta:</span><ul className="list-disc pl-4 text-term-faint">{(r.missing.length ? r.missing : ["—"]).map((e, i) => <li key={i}>{e}</li>)}</ul></div>
        </div>
      )}
    </div>
  );
}

function RouteRow({ r }: { r: RouteEval }) {
  const tone = r.chosen ? "text-term-good" : r.available ? "text-term-accent" : "text-term-muted";
  return (
    <div className={`flex items-start gap-2 text-[12px] border-b border-term-border last:border-0 py-1.5 ${r.chosen ? "bg-term-good/5" : ""}`}>
      <span className={`font-mono text-[11px] font-semibold w-44 shrink-0 ${tone}`}>{ROUTE_NAME[r.id]}{r.chosen ? ` · ${money(r.amount)}` : ""}</span>
      <span className="text-term-muted">{r.chosen ? <b className="text-term-good">ELEGIDA. </b> : r.available ? <span className="text-term-accent">disponible. </span> : <span className="text-term-faint">descartada. </span>}{r.chosen || r.available ? r.merit : r.whyNot}</span>
    </div>
  );
}

export function AdvisorExecutive({ report: r }: { report: Advisor2Report }) {
  const [showRules, setShowRules] = useState(false);
  const stanceTone = r.stance === "desplegar" ? "text-term-good" : r.stance === "parcial" ? "text-term-accent" : "text-term-muted";
  return (
    <div className="flex flex-col gap-3">
      <Panel title="Recomendación del mes · Investment Advisor 2.2">
        <div className={`text-sm ${stanceTone} font-medium leading-snug`}>{r.monthSummary}</div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">
          <div className="rounded border border-term-border bg-term-panel2/40 p-2.5"><div className="text-[10px] text-term-muted">Cartera</div><div className="text-base font-mono text-term-fg">{money(r.portfolioValue)}</div></div>
          <div className="rounded border border-term-border bg-term-panel2/40 p-2.5"><div className="text-[10px] text-term-muted">Aporte a asignar</div><div className="text-base font-mono text-term-fg">{money(r.cash)}</div></div>
          <div className="rounded border border-term-good/40 bg-term-good/5 p-2.5"><div className="text-[10px] text-term-muted">A desplegar</div><div className="text-base font-mono text-term-good">{money(r.invested)}</div></div>
          <div className="rounded border border-term-border bg-term-panel2/40 p-2.5"><div className="text-[10px] text-term-muted">Mantener en liquidez</div><div className="text-base font-mono text-term-fg">{money(r.cashKept)}</div></div>
        </div>
      </Panel>

      <Panel title="Comparación de rutas del aporte (A / B / C / D)">
        {r.routes.map((rt) => <RouteRow key={rt.id} r={rt} />)}
      </Panel>

      <Panel title={`Propuesta de asignación del aporte (${money(r.cash)})`}>
        {r.allocation.length === 0 ? (
          <div className="text-sm text-term-muted">Sin asignación: mantener los {money(r.cash)} en liquidez es la decisión justificada (ver comparación de rutas).</div>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead><tr className="border-b border-term-border text-left text-xs uppercase text-term-muted">
                <th className="py-1.5">Instrumento</th><th>Ruta</th><th className="text-right">Monto</th><th className="text-right">% aporte</th><th className="text-right">Peso result.</th></tr></thead>
              <tbody>
                {r.allocation.map((a) => (
                  <tr key={a.ticker} className="border-b border-term-border last:border-0">
                    <td className="py-2 font-mono">{a.ticker}</td>
                    <td className="text-term-muted text-xs">{a.route === "C" ? "ETF divers." : a.route === "A" ? "Aumentar" : "Nueva"}</td>
                    <td className="text-right tabnum font-mono">{money(a.amount)}</td>
                    <td className="text-right tabnum">{pct(a.pctOfCash)}</td>
                    <td className="text-right tabnum text-term-muted">{pct(a.newWeight)}</td>
                  </tr>
                ))}
                <tr className="text-xs text-term-faint"><td className="py-1.5" colSpan={2}>Liquidez retenida</td><td className="text-right tabnum">{money(r.cashKept)}</td><td className="text-right tabnum">{pct(r.cash > 0 ? r.cashKept / r.cash : 0)}</td><td></td></tr>
              </tbody>
            </table>
            <div className="mt-2 grid gap-1">{r.allocation.map((a) => <div key={a.ticker} className="text-[11px] text-term-faint"><b className="text-term-muted font-mono">{a.ticker}:</b> {a.reason} {a.marginLine}</div>)}</div>
            <div className="text-[10px] text-term-faint mt-2">Suma exacta: {money(r.invested)} asignados + {money(r.cashKept)} en liquidez = {money(r.cash)}.</div>
          </>
        )}
      </Panel>

      <Panel title="Riesgo y concentración efectiva · antes → después">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="rounded border border-term-border bg-term-panel2/40 p-3"><div className="text-[11px] text-term-muted mb-1">Antes</div><div className="font-mono text-term-fg">{r.before.effN.toFixed(1)} nombres efectivos</div><div className="text-[11px] text-term-muted mt-1">Mayor peso: {r.before.topTicker ?? "—"} {pct(r.before.topWeight)}</div></div>
          <div className="rounded border border-term-accent/40 bg-term-panel2/60 p-3"><div className="text-[11px] text-term-muted mb-1">Después</div><div className="font-mono text-term-fg">{r.after.effN.toFixed(1)} nombres efectivos</div><div className="text-[11px] text-term-muted mt-1">Mayor peso: {r.after.topTicker ?? "—"} {pct(r.after.topWeight)}</div></div>
        </div>
        <div className="text-[10px] text-term-faint mt-2">{r.cashNote}</div>
      </Panel>

      <Panel title="Decisiones por instrumento · posición existente + aporte nuevo (toca para ver evidencia)">
        <div className="grid gap-2">{r.recommendations.map((rec) => <RecCard key={rec.ticker} r={rec} />)}</div>
      </Panel>

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
        </Panel>
      )}

      <Panel title="Advertencias por datos incompletos y reglas de decisión"
        right={<button onClick={() => setShowRules(!showRules)} className="text-xs text-term-muted hover:text-term-fg">{showRules ? "Ocultar reglas" : "Ver reglas y pesos"}</button>}>
        <ul className="list-disc pl-4 text-[11px] text-term-warn leading-snug">
          {r.warnings.map((w, i) => <li key={i} className={w.startsWith("Fair Value V1") ? "text-term-faint" : ""}>{w}</li>)}
        </ul>
        {showRules && (
          <div className="mt-3 pt-2 border-t border-term-border">
            <ul className="list-disc pl-4 text-[11px] text-term-muted leading-snug">{r.rules.map((w, i) => <li key={i}>{w}</li>)}</ul>
            <div className="text-[10px] text-term-faint mt-2">Datos: {r.dataUsed.join(" · ")}</div>
          </div>
        )}
      </Panel>
    </div>
  );
}
