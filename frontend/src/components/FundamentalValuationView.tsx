// P1.9 — Vista de valoración fundamental (SOLO render del payload del backend). No calcula nada.
// Experimental: no es recomendación; no sustituye el Fair Value productivo ni Advisor.
import { useState } from "react";
import { Panel } from "./Panel";
import { money, pct, num } from "../format";
import {
  type FundValPayload, type CompanyValuation, type ModelBlock,
  MODEL_LABEL, confidenceTone, availableModels,
} from "../core/fundval";

function ModelCard({ m }: { m: ModelBlock }) {
  const label = MODEL_LABEL[m.modelo] ?? m.modelo;
  if (m.disponible === false || m.fair_value_usd == null) {
    return (
      <div className="rounded border border-term-border/60 p-3 opacity-70">
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-term-muted mt-1">No disponible — {m.motivo ?? "sin datos"}</div>
        {m.razones?.length ? (
          <ul className="text-[11px] text-term-muted mt-1 list-disc pl-4">
            {m.razones.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        ) : null}
      </div>
    );
  }
  const productive = m.modelo === "DCF_productivo";
  return (
    <div className="rounded border border-term-border/60 p-3">
      <div className="flex items-baseline justify-between">
        <div className="text-sm font-medium">{label}</div>
        {m.confianza ? (
          <span className={`text-[11px] ${confidenceTone(m.confianza)}`}>confianza: {m.confianza}</span>
        ) : null}
      </div>
      <div className="mt-2 flex items-baseline gap-3">
        <span className="text-xl font-semibold">{money(m.fair_value_usd, "USD")}</span>
        {m.margen_seguridad_pct != null ? (
          <span className={m.margen_seguridad_pct >= 0 ? "text-emerald-400 text-sm" : "text-rose-400 text-sm"}>
            margen seg. {pct(m.margen_seguridad_pct / 100)}
          </span>
        ) : null}
      </div>
      {!productive && (
        <>
          {m.escenarios ? (
            <div className="mt-2 text-xs text-term-muted">
              cons {money(m.escenarios.conservador, "USD")} · base {money(m.escenarios.base, "USD")} · opt{" "}
              {money(m.escenarios.optimista, "USD")}
            </div>
          ) : null}
          <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-term-muted">
            {m.wacc_pct != null ? <span>WACC {num(m.wacc_pct)}%</span> : null}
            {m.g_terminal_pct != null ? <span>g term. {num(m.g_terminal_pct)}%</span> : null}
            {m.peso_terminal_pct != null ? <span>peso terminal {num(m.peso_terminal_pct)}%</span> : null}
            {m.reverse_dcf_g1_pct != null ? <span>reverse-DCF g₁ {num(m.reverse_dcf_g1_pct)}%</span> : null}
            {m.reinversion ? <span className="col-span-2">reinversión: {m.reinversion}</span> : null}
          </div>
          {m.proyeccion_10a?.length ? (
            <table className="mt-2 w-full text-[11px]">
              <thead className="text-term-muted">
                <tr><th className="text-left">año</th><th className="text-right">g%</th>
                  <th className="text-right">margen%</th><th className="text-right">ROIC%</th></tr>
              </thead>
              <tbody>
                {m.proyeccion_10a.map((y) => (
                  <tr key={y.año}>
                    <td>{y.año}</td><td className="text-right">{num(y.g_pct)}</td>
                    <td className="text-right">{num(y.margen_pct)}</td>
                    <td className="text-right">{y.roic_pct != null ? num(y.roic_pct, 0) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {m.limitaciones?.length ? (
            <ul className="mt-2 text-[11px] text-amber-300/80 list-disc pl-4">
              {m.limitaciones.map((l, i) => <li key={i}>{l}</li>)}
            </ul>
          ) : null}
        </>
      )}
      {m.procedencia ? (
        <div className="mt-2 text-[10px] text-term-muted border-t border-term-border/40 pt-1">
          {m.procedencia.fuente ?? ""} · {m.procedencia.moneda} · {m.procedencia.fecha}
        </div>
      ) : null}
      {m.nota ? <div className="text-[10px] text-term-muted mt-1">{m.nota}</div> : null}
    </div>
  );
}

function CompanyCard({ c }: { c: CompanyValuation }) {
  const avail = availableModels(c);
  return (
    <Panel title={`${c.ticker} · ${c.ccy} · ${money(c.precio, "USD")}`}>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {c.modelos.map((m, i) => <ModelCard key={i} m={m} />)}
      </div>
      {c.comparacion && avail.length > 1 ? (
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
        Valoración fundamental <strong>experimental</strong> (P1.9). No sustituye el Fair Value
        productivo ni las recomendaciones de Advisor. No calibrada a mercado ni a terceros.
        {data.generado ? ` Generado: ${data.generado}.` : ""}
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
