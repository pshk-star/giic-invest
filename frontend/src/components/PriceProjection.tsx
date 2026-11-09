import { useMemo } from "react";
import { Panel } from "./Panel";
import type { PriceBar } from "../data";
import { buildAssets, forecast, hasMixedAdjustment } from "../core/forecast";
import { money, pct } from "../format";

// Confianza CUALITATIVA (no un % inventado): depende del tamaño muestral y del horizonte.
// Horizontes largos y muestras cortas ⇒ menor confianza. Nunca se presenta como alfa validado.
function horizonConfidence(days: number, nObs: number): "Media" | "Baja" {
  if (nObs < 250) return "Baja";
  return days <= 63 ? "Media" : "Baja";
}
const confCls = (c: string) => (c === "Media" ? "text-term-info border-term-info/40" : "text-term-warn border-term-warn/40");

// Abanico de incertidumbre: banda P5–P95 + mediana, en unidades de PRECIO (valueUsd = precio).
function Fan({ band, price, height = 150 }: {
  band: { day: number; p5: number; p50: number; p95: number }[]; price: number; height?: number;
}) {
  const W = 640, H = height, padT = 10, padB = 18, padL = 46, padR = 10;
  if (band.length < 2) return <div className="text-[11px] text-term-muted py-6 text-center">Sin banda suficiente</div>;
  const lo = Math.min(price, ...band.map((b) => b.p5));
  const hi = Math.max(price, ...band.map((b) => b.p95));
  const maxDay = band[band.length - 1].day;
  const x = (d: number) => padL + ((d - 1) / Math.max(1, maxDay - 1)) * (W - padL - padR);
  const y = (v: number) => H - padB - ((v - lo) / Math.max(1e-9, hi - lo)) * (H - padT - padB);
  const area = band.map((b) => `${x(b.day).toFixed(1)},${y(b.p95).toFixed(1)}`).join(" ")
    + " " + [...band].reverse().map((b) => `${x(b.day).toFixed(1)},${y(b.p5).toFixed(1)}`).join(" ");
  const mid = band.map((b, i) => `${i ? "L" : "M"}${x(b.day).toFixed(1)},${y(b.p50).toFixed(1)}`).join(" ");
  const yp = y(price);
  const ticks = [0, 63, 126, 189, 252].filter((d) => d <= maxDay);
  const monthLabel: Record<number, string> = { 0: "hoy", 63: "3m", 126: "6m", 189: "9m", 252: "12m" };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }}>
      <line x1={padL} x2={W - padR} y1={y(hi)} y2={y(hi)} stroke="#263142" strokeWidth={1} strokeDasharray="2 3" />
      <line x1={padL} x2={W - padR} y1={y(lo)} y2={y(lo)} stroke="#263142" strokeWidth={1} strokeDasharray="2 3" />
      <text x={padL - 5} y={y(hi) + 3} fontSize={9} fill="#8b95a5" textAnchor="end">{money(hi)}</text>
      <text x={padL - 5} y={y(lo) + 3} fontSize={9} fill="#8b95a5" textAnchor="end">{money(lo)}</text>
      {/* precio actual (ancla; sin convergencia al Fair Value) */}
      <line x1={padL} x2={W - padR} y1={yp} y2={yp} stroke="#4ea1d3" strokeWidth={1} strokeDasharray="3 2" opacity={0.7} />
      <text x={W - padR} y={yp - 3} fontSize={9} fill="#4ea1d3" textAnchor="end">precio {money(price)}</text>
      <polygon points={area} fill="#4ea1d3" opacity={0.14} />
      <path d={mid} fill="none" stroke="#4ea1d3" strokeWidth={1.75} />
      {ticks.map((d) => (
        <text key={d} x={x(Math.max(1, d))} y={H - 4} fontSize={9} fill="#8b95a5"
          textAnchor={d === 0 ? "start" : d >= maxDay ? "end" : "middle"}>{monthLabel[d] ?? ""}</text>
      ))}
    </svg>
  );
}

export function PriceProjection({ ticker, price, bars, hasModelSignal }: {
  ticker: string; price: number | null; bars: PriceBar[]; hasModelSignal?: boolean;
}) {
  const mixed = useMemo(() => hasMixedAdjustment(bars), [bars]);
  const result = useMemo(() => {
    if (!price || bars.length < 61 || mixed) return null;
    const assets = buildAssets({ [ticker]: bars }, { [ticker]: price });
    return assets.length ? forecast(assets, { drift: "neutral" }) : null;
  }, [ticker, bars, price, mixed]);

  return (
    <Panel title="Proyección de precio · 12 meses">
      <p className="text-[11px] text-term-muted mb-2 leading-snug">
        <b>Escenario estadístico</b>, no una predicción de alfa ni un precio objetivo. Simulación histórica
        (bootstrap por bloques sobre <b>precios ajustados</b>, sin look-ahead) con <b>retorno esperado supuesto 0%</b>
        (neutral): el centro se mantiene cerca del precio actual y <b>no</b> converge al Fair Value. El rango refleja
        la volatilidad histórica. Distinto del valor intrínseco (arriba) y de la señal experimental del modelo (abajo).
      </p>

      {!price ? (
        <p className="text-sm text-term-warn">Sin precio actual: no se puede anclar la proyección.</p>
      ) : mixed ? (
        <p className="text-sm text-term-crit">Serie con ajuste inconsistente (mezcla precios ajustados y sin ajustar): se excluye hasta re-ingerir el historial ajustado. No se proyecta con datos no comparables.</p>
      ) : bars.length < 61 ? (
        <p className="text-sm text-term-warn">Historial insuficiente ({bars.length} sesiones; se requieren ≥61). No se proyecta.</p>
      ) : !result || !result.horizons.length ? (
        <p className="text-sm text-term-warn">No fue posible proyectar con el historial disponible.</p>
      ) : (
        <>
          <div className="overflow-x-auto mb-3">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="border-b border-term-border text-left text-xs uppercase text-term-muted">
                  <th className="py-1.5">Horizonte</th>
                  <th className="text-right">Precio central (P50)</th>
                  <th className="text-right">Variación esper.</th>
                  <th className="text-right">Rango P5–P95</th>
                  <th className="text-right">Confianza</th>
                </tr>
              </thead>
              <tbody>
                {result.horizons.map((h) => {
                  const c = horizonConfidence(h.days, result.nObs);
                  return (
                    <tr key={h.days} className="border-b border-term-border last:border-0">
                      <td className="py-2">{h.label}</td>
                      <td className="text-right tabnum">{money(h.valP50)}</td>
                      <td className={`text-right tabnum ${h.retP50 >= 0 ? "text-term-good" : "text-term-crit"}`}>{h.retP50 >= 0 ? "+" : ""}{pct(h.retP50)}</td>
                      <td className="text-right tabnum text-term-muted">{money(h.valP5)} … {money(h.valP95)}<br /><span className="text-[10px] text-term-faint">{pct(h.retP5)} … +{pct(h.retP95)}</span></td>
                      <td className="text-right"><span className={`inline-block px-2 py-[1px] rounded border text-[11px] font-mono ${confCls(c)}`}>{c}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="rounded border border-term-border bg-term-panel2/30 p-3 mb-2">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] text-term-muted font-head uppercase tracking-wide">Trayectoria y abanico de incertidumbre (P5–P95)</span>
              <span className="text-[10px] text-term-faint">vol. anual {pct(result.annVol)} · {result.nObs} sesiones</span>
            </div>
            <Fan band={result.band} price={price} />
          </div>

          <ul className="text-[10px] text-term-faint leading-snug list-disc pl-4">
            <li>Rangos = percentiles de la distribución histórica, <b>no</b> probabilidades predictivas calibradas ni rendimiento demostrado.</li>
            <li>El centro no es un pronóstico de rentabilidad: con retorno esperado 0%, el valor intrínseco (Fair Value) y la proyección de precio son lecturas independientes.</li>
            <li>{hasModelSignal
              ? "Señal experimental A/B disponible (retorno relativo al universo, no validada): ver el panel del modelo más abajo. No se incorpora a esta proyección."
              : "Sin señal del modelo experimental A/B para este instrumento; esta proyección es puramente estadística."}</li>
          </ul>
        </>
      )}
    </Panel>
  );
}
