// Fuente de precios de VALORACIÓN unificada para Dashboard y Mi Cartera.
// Regla única (la misma en ambas pantallas): por cada ticker se usa la cotización
// reciente (tabla quotes) si existe y es válida; si no, el último cierre EOD (tabla
// prices). Devuelve además metadatos para mostrar timestamp y si el valor es INTRADÍA
// (mercado abierto) o de CIERRE, de forma honesta y determinística.
import type { PriceInfo } from "./portfolio-tx";
import { classifyQuote, type Freshness } from "./quotefmt";

// Forma mínima de una cotización (estructuralmente compatible con QuoteRow).
export interface QuoteLike {
  price: number;
  previous_close: number | null;
  quote_time: string;
  market_state: string | null;
  delayed: boolean;
  currency: string;
}

export type ValuationKind = "intraday" | "close" | "mixed" | "none";
export type ValuationSource = "quotes+eod" | "quotes" | "eod" | "none";

export interface ValuationMeta {
  asOfDate: string | null;   // fecha de referencia (la más reciente usada)
  asOfTs: string | null;     // timestamp completo de la cotización más fresca (si hay)
  kind: ValuationKind;       // intradía / cierre / mixto / sin datos
  anyDelayed: boolean;       // alguna cotización marcada como retrasada
  freshness: Freshness | "none";
  label: string;             // descripción legible del estado
  source: ValuationSource;
  nQuotes: number;           // tickers valorados con cotización
  nEod: number;              // tickers valorados solo con cierre EOD
}

export function mergeValuation(
  tickers: string[],
  eod: Record<string, PriceInfo>,
  quotes: Record<string, QuoteLike>,
  nowMs: number = Date.now(),
): { prices: Record<string, PriceInfo>; meta: ValuationMeta } {
  const prices: Record<string, PriceInfo> = { ...eod };
  const kinds = new Set<string>();
  let nQuotes = 0, nEod = 0, anyDelayed = false;
  let freshestTs: string | null = null;
  let freshestQuote: QuoteLike | null = null;

  for (const t of tickers) {
    const q = quotes[t];
    if (q && Number.isFinite(q.price) && q.price > 0 && q.quote_time) {
      prices[t] = { close: q.price, as_of: q.quote_time.slice(0, 10), currency: q.currency };
      nQuotes++;
      if (q.delayed) anyDelayed = true;
      const cl = classifyQuote(q.quote_time, q.market_state, q.delayed, nowMs);
      kinds.add(cl.freshness === "live" ? "intraday" : "close");
      if (!freshestTs || q.quote_time > freshestTs) { freshestTs = q.quote_time; freshestQuote = q; }
    } else if (eod[t]) {
      nEod++;
      kinds.add("close");
    }
  }

  let kind: ValuationKind = "none";
  if (kinds.size === 1) kind = [...kinds][0] as ValuationKind;
  else if (kinds.size > 1) kind = "mixed";

  const source: ValuationSource =
    nQuotes > 0 && nEod > 0 ? "quotes+eod" : nQuotes > 0 ? "quotes" : nEod > 0 ? "eod" : "none";

  let freshness: Freshness | "none" = "none";
  let label = "sin precios";
  let asOfDate: string | null = null;

  if (freshestQuote && freshestTs) {
    const cl = classifyQuote(freshestTs, freshestQuote.market_state, freshestQuote.delayed, nowMs);
    freshness = cl.freshness;
    label = cl.label;
    asOfDate = freshestTs.slice(0, 10);
  } else {
    const dates = (tickers.map((t) => eod[t]?.as_of).filter(Boolean) as string[]).sort();
    if (dates.length) { asOfDate = dates[dates.length - 1]; freshness = "close"; label = "último cierre (EOD)"; }
  }

  return { prices, meta: { asOfDate, asOfTs: freshestTs, kind, anyDelayed, freshness, label, source, nQuotes, nEod } };
}
