import { useMemo } from "react";
import { Panel } from "./Panel";
import type { FundamentalsPayload, DcfScenario } from "../core/valuation";
import { fairValueDCF, DISCOUNT_BASE } from "../core/valuation";
import { num, pct } from "../format";

// Escala en moneda nativa (no fuerza USD).
function sc(v: number | null | undefined, ccy?: string | null): string {
  if (v === null || v === undefined || !isFinite(v)) return "—";
  const a = Math.abs(v), s = v < 0 ? "-" : "", c = ccy || "";
  if (a >= 1e12) return `${s}${(a / 1e12).toFixed(2)} B ${c}`.trim();
  if (a >= 1e9) return `${s}${(a / 1e9).toFixed(a / 1e9 >= 100 ? 0 : 1)} mm ${c}`.trim();
  if (a >= 1e6) return `${s}${(a / 1e6).toFixed(0)} M ${c}`.trim();
  return `${s}${a.toFixed(0)} ${c}`.trim();
}
const vps = (v: number | null | undefined, ccy: string) =>
  v === null || v === undefined || !isFinite(v) ? "—" : `${num(v, 2)} ${ccy}`;
const marginCls = (m: number) => (m >= 0 ? "text-term-good" : "text-term-crit");

function ScenarioCard({ s, ccy, comparable }: { s: DcfScenario; ccy: string; comparable: boolean }) {
  const emphasis = s.name === "Base";
  return (
    <div className={`rounded border p-3 flex flex-col gap-1.5 ${emphasis ? "border-term-accent/50 bg-term-panel2/60" : "border-term-border bg-term-panel2/30"}`}>
      <div className="flex items-center justify-between">
        <span className={`text-[11px] font-head uppercase tracking-wide ${emphasis ? "text-term-accent" : "text-term-muted"}`}>{s.name}</span>
        {comparable && s.marginVsPrice != null && (
          <span className={`text-xs font-mono tabnum ${marginCls(s.marginVsPrice)}`}>{s.marginVsPrice >= 0 ? "+" : ""}{pct(s.marginVsPrice)}</span>
        )}
      </div>
      <div className="text-xl font-mono text-term-fg tabnum leading-none">{vps(s.run.perShare, ccy)}</div>
      <div className="text-[10px] text-term-faint leading-tight">
        crec. {pct(s.a.g1, 0)}→{pct(s.a.gTerminal, 1)} · tasa {pct(s.a.discount, 1)}
      </div>
    </div>
  );
}

export function FairValue({ fund, price, priceCcy, priceAsOf }: {
  fund: FundamentalsPayload; price: number | null; priceCcy: string | null; priceAsOf?: string | null;
}) {
  const fv = useMemo(() => fairValueDCF(fund, price, priceCcy), [fund, price, priceCcy]);
  const ccy = fund.history?.currency ?? fund.currency ?? "USD";

  if (!fv.available) {
    return (
      <Panel title="Fair Value (DCF · FCF descontado)">
        <div className="rounded border border-term-warn/40 bg-term-warn/10 px-3 py-2 text-sm text-term-warn">
          <b>Valoración no disponible.</b> {fv.reason}
        </div>
      </Panel>
    );
  }

  const base = fv.base!, inp = fv.inputs!, sens = fv.sensitivity!;
  const comparable = !!fv.priceComparable;
  const baseMargin = base.marginVsPrice;
  // Rejilla de sensibilidad: filas = tasa (−1/0/+1pp), columnas = crec. terminal (−0.5/0/+0.5pp)
  const discs = Array.from(new Set(sens.map((c) => c.discount))).sort((a, b) => a - b);
  const gts = Array.from(new Set(sens.map((c) => c.gTerminal))).sort((a, b) => a - b);
  const cellOf = (d: number, g: number) => sens.find((c) => c.discount === d && c.gTerminal === g)?.perShare ?? null;
  const confCls = fv.confidence === "Alta" ? "text-term-good border-term-good/40"
    : fv.confidence === "Media" ? "text-term-info border-term-info/40" : "text-term-warn border-term-warn/40";

  return (
    <Panel title="Fair Value (DCF · FCF descontado)">
      {/* Cabecera: precio vs Fair Value base + margen de seguridad */}
      <div className="flex flex-wrap items-stretch gap-3 mb-3">
        <div className="flex-1 min-w-[140px] rounded border border-term-border bg-term-panel2/40 p-3">
          <div className="text-[11px] text-term-muted">Precio actual</div>
          <div className="text-lg font-mono text-term-fg tabnum">{price != null ? `${num(price, 2)} ${priceCcy ?? ""}`.trim() : "—"}</div>
          <div className="text-[10px] text-term-faint">{priceAsOf ? `al ${priceAsOf}` : "cotización"}</div>
        </div>
        <div className="flex-1 min-w-[140px] rounded border border-term-accent/40 bg-term-panel2/60 p-3">
          <div className="text-[11px] text-term-muted">Fair Value (base)</div>
          <div className="text-lg font-mono text-term-fg tabnum">{vps(base.run.perShare, ccy)}</div>
          <div className="text-[10px] text-term-faint">por acción · {ccy}</div>
        </div>
        <div className="flex-1 min-w-[140px] rounded border border-term-border bg-term-panel2/40 p-3">
          <div className="text-[11px] text-term-muted">Margen de seguridad (base)</div>
          {comparable && baseMargin != null ? (
            <div className={`text-lg font-mono tabnum ${marginCls(baseMargin)}`}>{baseMargin >= 0 ? "+" : ""}{pct(baseMargin)}</div>
          ) : (
            <div className="text-xs text-term-warn leading-tight mt-1">Requiere FX fechado<br /><span className="text-term-faint">precio {priceCcy ?? "s/d"} · valor {ccy}</span></div>
          )}
          <div className="text-[10px] text-term-faint">{comparable ? "valor/precio − 1" : "no calculado"}</div>
        </div>
      </div>

      {/* Escenarios */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        {fv.scenarios!.map((s) => <ScenarioCard key={s.name} s={s} ccy={ccy} comparable={comparable} />)}
      </div>

      {/* Supuestos y observado */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
        <div className="rounded border border-term-border bg-term-panel2/30 p-3">
          <div className="text-[11px] text-term-good font-head uppercase tracking-wide mb-1.5">Observado (datos)</div>
          <dl className="text-[11px] text-term-muted grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt>FCF base norm.</dt><dd className="text-right text-term-fg font-mono">{sc(inp.baseFcf, ccy)}</dd>
            <dt className="text-term-faint">· método</dt><dd className="text-right text-term-faint">{inp.baseFcfMethod}</dd>
            <dt>FCF último año</dt><dd className="text-right text-term-fg font-mono">{sc(inp.lastFcf, ccy)}</dd>
            <dt>Deuda neta</dt><dd className="text-right text-term-fg font-mono">{inp.netDebtKnown ? sc(inp.netDebt, ccy) : "n/d → 0"}</dd>
            <dt>Acciones diluidas</dt><dd className="text-right text-term-fg font-mono">{sc(inp.shares, "")}</dd>
            <dt>Histórico FCF</dt><dd className="text-right text-term-fg font-mono">{inp.histYears} años</dd>
          </dl>
        </div>
        <div className="rounded border border-term-border bg-term-panel2/30 p-3">
          <div className="text-[11px] text-term-accent font-head uppercase tracking-wide mb-1.5">Supuestos (modelo)</div>
          <dl className="text-[11px] text-term-muted grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt>Crec. base (CAGR ingresos)</dt><dd className="text-right text-term-fg font-mono">{pct(inp.baseGrowth)}</dd>
            <dt>Tasa descuento base</dt><dd className="text-right text-term-fg font-mono">{pct(base.a.discount)}</dd>
            <dt className="text-term-faint">· rf + β·ERP</dt><dd className="text-right text-term-faint">4.0% + 1.1·5.0%</dd>
            <dt>Crec. terminal</dt><dd className="text-right text-term-fg font-mono">{pct(base.a.gTerminal)}</dd>
            <dt>Horizonte explícito</dt><dd className="text-right text-term-fg font-mono">{base.a.years} años</dd>
            <dt>Valor en terminal</dt><dd className="text-right text-term-fg font-mono">{pct(base.run.terminalWeight, 0)}</dd>
          </dl>
        </div>
      </div>

      {/* Sensibilidad + DCF inverso */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="rounded border border-term-border bg-term-panel2/30 p-3">
          <div className="text-[11px] text-term-muted font-head uppercase tracking-wide mb-1.5">Sensibilidad · valor/acción ({ccy})</div>
          <table className="w-full text-[11px] font-mono tabnum">
            <thead>
              <tr className="text-term-faint">
                <th className="text-left font-normal">tasa ╲ g<sub>term</sub></th>
                {gts.map((g) => <th key={g} className="text-right font-normal">{pct(g, 1)}</th>)}
              </tr>
            </thead>
            <tbody>
              {discs.map((d) => (
                <tr key={d}>
                  <td className="text-term-muted">{pct(d, 1)}</td>
                  {gts.map((g) => {
                    const v = cellOf(d, g);
                    const isBase = Math.abs(d - base.a.discount) < 1e-9 && Math.abs(g - base.a.gTerminal) < 1e-9;
                    return <td key={g} className={`text-right ${isBase ? "text-term-accent font-semibold" : "text-term-fg"}`}>{v != null ? num(v, 0) : "—"}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="rounded border border-term-border bg-term-panel2/30 p-3 flex flex-col gap-2">
          <div className="text-[11px] text-term-muted font-head uppercase tracking-wide">Lectura inversa & confianza</div>
          <div className="text-[11px] text-term-fg leading-snug">
            {comparable && fv.impliedGrowth != null ? (
              <>Al precio actual, el mercado descuenta un crecimiento de FCF de <b className="text-term-accent">~{pct(fv.impliedGrowth, 1)}</b> (tramo explícito, tasa {pct(base.a.discount, 1)}, terminal {pct(base.a.gTerminal, 1)}). Compáralo con el CAGR de ingresos observado ({pct(inp.baseGrowth, 1)}).</>
            ) : (
              <span className="text-term-faint">Crecimiento implícito no calculado: requiere precio en moneda de reporte ({ccy}).</span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-auto pt-1">
            <span className="text-[11px] text-term-muted">Confianza:</span>
            <span className={`inline-block px-2 py-[1px] rounded border text-[11px] font-mono ${confCls}`}>{fv.confidence}</span>
          </div>
          {fv.confidenceNotes!.length > 0 && (
            <ul className="text-[10px] text-term-faint leading-tight list-disc pl-4">
              {fv.confidenceNotes!.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
        </div>
      </div>

      <p className="text-[10px] text-term-faint mt-3 leading-snug">
        DCF determinístico sobre FCF = OCF − CAPEX (moneda de reporte {ccy}); un único flujo y una única tasa.
        Los escenarios son <b>supuestos</b>, no predicciones. No usa EPS ambiguos, campos en cuarentena ni interinos
        no aptos. Base de tasa: coste de capital {pct(DISCOUNT_BASE, 1)} (rf + β·ERP). Para financieras y datos
        insuficientes, la valoración se marca como no disponible.
      </p>
    </Panel>
  );
}
