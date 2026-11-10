// P1.9 — Vista de valoración fundamental (SOLO render del payload del backend). No calcula nada.
// Experimental: no es recomendación; no sustituye el Fair Value productivo ni Advisor.
// Los 4 Fair Values y sus márgenes de seguridad quedan SIEMPRE visibles; el detalle financiero va
// en secciones expandibles. Un margen positivo con confianza baja NO se pinta como señal de compra.
import { useState } from "react";
import { Panel } from "./Panel";
import { money, num } from "../format";
import {
  type FundValPayload, type CompanyValuation, type ModelBlock,
  MODEL_LABEL, confidenceTone, marginView,
} from "../core/fundval";

function SummaryCell({ m }: { m: ModelBlock }) {
  const label = MODEL_LABEL[m.modelo] ?? m.modelo;
  if (m.disponible === false || m.fair_value_usd == null) {
    return (
      <div className="rounded border border-term-border/60 p-3 opacity-60">
        <div className="text-xs font-medium">{label}</div>
        <div className="text-lg font-semibold text-term-muted mt-1">—</div>
        <div className="text-[11px] text-term-muted">No disponible</div>
      </div>
    );
  }
  const mv = marginView(m.margen_seguridad_pct, m.confianza);
  return (
    <div className="rounded border border-term-border/60 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-xs font-medium">{label}</div>
        {m.confianza ? <span className={`text-[10px] ${confidenceTone(m.confianza)}`}>{m.confianza}</span> : null}
      </div>
      <div className="text-xl font-semibold mt-1">{money(m.fair_value_usd, "USD")}</div>
      <div className={`text-[11px] ${mv.cls}`}>{mv.label}</div>
    </div>
  );
}

function Detail({ m }: { m: ModelBlock }) {
  if (m.disponible === false || m.fair_value_usd == null) {
    return (
      <div className="text-xs text-term-muted">
        {MODEL_LABEL[m.modelo] ?? m.modelo}: no disponible — {m.motivo ?? "sin datos"}
        {m.razones?.length ? ` (${m.razones.join("; ")})` : ""}
      </div>
    );
  }
  if (m.modelo === "DCF_productivo") {
    return <div className="text-xs text-term-muted">DCF productivo: referencia de la tubería productiva (no experimental). {m.procedencia?.fuente}</div>;
  }
  return (
    <details className="rounded border border-term-border/50 px-3 py-2">
      <summary className="cursor-pointer text-xs font-medium">
        {MODEL_LABEL[m.modelo] ?? m.modelo} — detalle financiero
      </summary>
      <div className="mt-2 space-y-2">
        {m.escenarios ? (
          <div className="text-xs text-term-muted">
            Escenarios · cons {money(m.escenarios.conservador, "USD")} · base {money(m.escenarios.base, "USD")} · opt {money(m.escenarios.optimista, "USD")}
          </div>
        ) : null}
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-term-muted">
          {m.wacc_pct != null ? <span>WACC {num(m.wacc_pct)}%</span> : null}
          {m.g_terminal_pct != null ? <span>g terminal {num(m.g_terminal_pct)}%</span> : null}
          {m.peso_terminal_pct != null ? <span>peso terminal {num(m.peso_terminal_pct)}%</span> : null}
          {m.reverse_dcf_g1_pct != null ? <span>reverse-DCF g₁ {num(m.reverse_dcf_g1_pct)}%</span> : null}
          {m.reinversion ? <span className="col-span-2">reinversión: {m.reinversion}</span> : null}
        </div>
        {m.proyeccion_10a?.length ? (
          <table className="w-full text-[11px]">
            <thead className="text-term-muted">
              <tr><th className="text-left">año</th><th className="text-right">g%</th><th className="text-right">margen%</th><th className="text-right">ROIC%</th></tr>
            </thead>
            <tbody>
              {m.proyeccion_10a.map((y) => (
                <tr key={y.año}><td>{y.año}</td><td className="text-right">{num(y.g_pct)}</td>
                  <td className="text-right">{num(y.margen_pct)}</td>
                  <td className="text-right">{y.roic_pct != null ? num(y.roic_pct, 0) : "—"}</td></tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {m.limitaciones?.length ? (
          <ul className="text-[11px] text-amber-300/80 list-disc pl-4">
            {m.limitaciones.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        ) : null}
        {m.procedencia ? (
          <div className="text-[10px] text-term-muted border-t border-term-border/40 pt-1">
            {m.procedencia.fuente ?? ""} · {m.procedencia.moneda} · {m.procedencia.fecha}
          </div>
        ) : null}
      </div>
    </details>
  );
}

function CompanyCard({ c }: { c: CompanyValuation }) {
  return (
    <Panel title={`${c.ticker} · ${c.ccy} · ${money(c.precio, "USD")}`}>
      {/* Resumen SIEMPRE visible: 4 Fair Values + margen de seguridad */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {c.modelos.map((m, i) => <SummaryCell key={i} m={m} />)}
      </div>
      {/* Detalle en secciones expandibles */}
      <div className="mt-3 space-y-2">
        {c.modelos.map((m, i) => <Detail key={i} m={m} />)}
      </div>
      {c.comparacion ? (
        <div className="mt-3 rounded bg-term-border/20 p-3 text-xs">
          <div className="font-medium mb-1">¿Por qué difieren?</div>
          <p className="text-term-muted">{c.comparacion.explicacion}</p>
        </div>
      ) : null}
    </Panel>
  );
}

export function FundamentalValuationView({ data }: { data: FundValPayload }) {
  const tickers = Object.keys(data.resultados);
  const [sel, setSel] = useState<string>(tickers[0] ?? "");
  const c = data.resultados[sel];
  return (
    <div className="space-y-3">
      <div className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-200">
        Valoración fundamental <strong>experimental</strong> (P1.9). No es recomendación de compra ni
        venta; no sustituye el Fair Value productivo ni las recomendaciones de Advisor. No calibrada a
        mercado ni a terceros.{data.generado ? ` Generado: ${data.generado}.` : ""}
      </div>
      <div className="flex flex-wrap gap-1">
        {tickers.map((t) => (
          <button key={t} onClick={() => setSel(t)}
            className={`px-2 py-1 text-xs rounded border ${t === sel ? "border-term-accent text-term-accent" : "border-term-border/60 text-term-muted"}`}>
            {t}
          </button>
        ))}
      </div>
      {c ? <CompanyCard c={c} /> : <div className="text-term-muted text-sm">Sin datos.</div>}
    </div>
  );
}
