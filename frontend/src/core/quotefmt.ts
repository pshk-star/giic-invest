// Clasificación de frescura de una cotización — DETERMINÍSTICA y honesta.
// Nunca llama "tiempo real" a algo retrasado. Distingue en vivo (retrasado) / cierre /
// desactualizado según la hora real de la cotización y el estado del mercado.

export type Freshness = "live" | "close" | "stale";

export interface QuoteDisplay {
  freshness: Freshness;
  label: string;
}

const STALE_HOURS = 36; // un viernes visto el lunes NO es "desactualizado" (fin de semana)

export function classifyQuote(
  quoteTimeISO: string | null | undefined,
  marketState: string | null | undefined,
  delayed: boolean,
  nowMs: number = Date.now()
): QuoteDisplay {
  if (!quoteTimeISO) return { freshness: "stale", label: "sin hora de cotización" };
  const t = Date.parse(quoteTimeISO);
  if (!isFinite(t)) return { freshness: "stale", label: "sin hora de cotización" };
  const ageH = (nowMs - t) / 3_600_000;
  if (ageH > STALE_HOURS) return { freshness: "stale", label: `desactualizado (hace ${Math.round(ageH)} h)` };
  if (marketState === "REGULAR") return { freshness: "live", label: delayed ? "mercado abierto · retrasado ~15 min" : "mercado abierto" };
  if (marketState === "PRE") return { freshness: "close", label: "pre-mercado · retrasado" };
  if (marketState === "POST") return { freshness: "close", label: "post-mercado · retrasado" };
  return { freshness: "close", label: "mercado cerrado · último cierre" };
}

// Formatea la hora de cotización en la zona del usuario, legible.
export function fmtQuoteTime(quoteTimeISO: string | null | undefined): string {
  if (!quoteTimeISO) return "—";
  const d = new Date(quoteTimeISO);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString("es-MX", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}
