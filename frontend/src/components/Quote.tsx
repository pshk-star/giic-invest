import { classifyQuote, fmtQuoteTime } from "../core/quotefmt";
import type { QuoteRow } from "../data";
import { money, num, pct } from "../format";

// Vista de cotización rica: precio, cambio del día, hora real, bolsa/moneda, estado del
// mercado, fuente y si es retrasada. Nunca dice "tiempo real" y nunca inventa valores.
export function QuoteView({ q }: { q: QuoteRow | null | undefined }) {
  if (!q) return <span className="text-sm text-term-warn">cotización pendiente (se toma en el próximo ciclo del job)</span>;
  const c = classifyQuote(q.quote_time, q.market_state, q.delayed);
  const chgTone = (q.change ?? 0) >= 0 ? "text-term-good" : "text-term-crit";
  const dot = c.freshness === "live" ? "bg-term-good" : c.freshness === "stale" ? "bg-term-crit" : "bg-term-warn";
  return (
    <div className="grid gap-1">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-xl tabnum text-term-fg">{money(q.price, q.currency)}</span>
        {q.change !== null && (
          <span className={`text-sm ${chgTone}`}>
            {q.change >= 0 ? "+" : ""}{money(q.change, q.currency)} ({q.change_pct !== null ? pct(q.change_pct) : "—"})
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-term-faint">
        <span className="flex items-center gap-1">
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${dot}`} />{c.label}
        </span>
        <span>{fmtQuoteTime(q.quote_time)}</span>
        {q.exchange && <span>{q.exchange}</span>}
        <span>{q.currency}</span>
        <span>fuente: {q.source}</span>
      </div>
      <div className="flex flex-wrap gap-x-3 text-[11px] text-term-muted">
        {q.previous_close !== null && <span>Cierre previo: {money(q.previous_close, q.currency)}</span>}
        {q.day_high !== null && <span>Máx: {money(q.day_high, q.currency)}</span>}
        {q.day_low !== null && <span>Mín: {money(q.day_low, q.currency)}</span>}
        {q.volume !== null && <span>Vol: {num(q.volume, 0)}</span>}
      </div>
    </div>
  );
}
