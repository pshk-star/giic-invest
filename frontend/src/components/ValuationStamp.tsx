import type { ValuationMeta } from "../core/price-source";
import { fmtQuoteTime } from "../core/quotefmt";

// Sello de valoración: muestra, de forma consistente en Dashboard y Mi Cartera, a qué
// hora y con qué tipo de precio (intradía / cierre) está valorada la cartera.
const KIND_LABEL: Record<string, string> = {
  intraday: "Intradía", close: "Cierre", mixed: "Mixto", none: "—",
};
const DOT: Record<string, string> = {
  live: "bg-term-good", close: "bg-term-warn", stale: "bg-term-crit", none: "bg-term-faint",
};

export function ValuationStamp({ meta }: { meta: ValuationMeta }) {
  if (meta.source === "none") {
    return <p className="text-xs text-term-muted">Sin precios disponibles para valorar.</p>;
  }
  const when = meta.asOfTs ? fmtQuoteTime(meta.asOfTs) : (meta.asOfDate ?? "—");
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-term-muted">
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${DOT[meta.freshness] ?? DOT.none}`} />
      <span className="font-semibold text-term-fg">{KIND_LABEL[meta.kind] ?? "—"}</span>
      <span>· {meta.label}</span>
      <span>· {when}</span>
      {meta.kind === "mixed" && (
        <span className="text-term-warn">· {meta.nQuotes} cotización / {meta.nEod} cierre</span>
      )}
    </div>
  );
}
