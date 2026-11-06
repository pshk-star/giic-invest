// Motor de OPORTUNIDADES (¿qué comprar HOY?) — criterio financiero, no por score.
//
// Reglas (puntos del usuario):
//  - Un score alto del scanner NO activa COMPRAR por sí solo (es atractivo relativo).
//  - COMPRAR exige evidencia de valoración favorable (o tesis de crecimiento verificable)
//    que justifique el PRECIO ACTUAL. ESPERAR = negocio interesante pero valoración/
//    riesgo-retorno insuficiente. INVESTIGAR = datos insuficientes o desactualizados.
//  - Montos por CONVICCIÓN (magnitud del descuento) + tope de concentración, NUNCA
//    reparto igual ni despliegue forzado del presupuesto. Mantener liquidez es válido.
//  - Distingue: buena empresa / atractivo relativo / oportunidad real al precio de hoy.
//  - No usa A/B/C. No inventa valoraciones ni márgenes de seguridad.

import type { CompanyValuation } from "./fundamental";

export type OppAction = "COMPRAR" | "ESPERAR" | "INVESTIGAR";

export interface OpportunityInput {
  ticker: string;
  name: string | null;
  sector: string | null;
  composite: number | null;      // score del scanner (atractivo relativo); contexto, no gatillo
  price: number | null;
  priceAsOf: string | null;
  valuation: CompanyValuation | null;   // de valuateCompany (EPS×P/E preliminar)
  roe: number | null;
  netMargin: number | null;
  heldWeight: number;            // peso directo actual (0 si no la tienes)
  effectiveWeight: number | null;
}

export interface OpportunityDecision {
  ticker: string;
  name: string | null;
  action: OppAction;
  price: number | null;
  priceAsOf: string | null;
  businessQuality: "buena" | "media" | "débil" | "n/d";
  relative: string;             // atractivo relativo (score)
  valuationLine: string;
  centralUpside: number | null;
  suggestedAmountUsd: number | null;   // solo COMPRAR
  suggestedTargetWeight: number | null;
  evidenceForBuyingNow: string[];
  missing: string[];
  whatWouldChange: string[];
  concentration: string;
  confidence: "alta" | "media" | "baja";
  priority: number;
  severity: number;
}

export interface OpportunityReport {
  decisions: OpportunityDecision[];
  cashAvailable: number;
  deployed: number;
  cashKept: number;
  note: string;
}

const BUY_UPSIDE = 0.15;   // descuento central mínimo para considerar COMPRAR
const pctS = (x: number) => `${(x * 100).toFixed(1)}%`;

function quality(roe: number | null, nm: number | null): OpportunityDecision["businessQuality"] {
  if (roe == null && nm == null) return "n/d";
  const r = roe ?? 0, m = nm ?? 0;
  if (r >= 0.15 && m >= 0.10) return "buena";
  if (r >= 0.08 || m >= 0.05) return "media";
  return "débil";
}

export function buildOpportunities(
  items: OpportunityInput[],
  cashAvailable: number,
  portfolioValue: number,
  maxWeightAsset: number,
): OpportunityReport {
  const denom = portfolioValue + Math.max(0, cashAvailable);
  const out: OpportunityDecision[] = items.map((it) => {
    const v = it.valuation;
    const bq = quality(it.roe, it.netMargin);
    const rel = it.composite != null ? `score ${Math.round(it.composite)}/100 (atractivo relativo, no es señal de compra)` : "sin score";
    const base: OpportunityDecision = {
      ticker: it.ticker, name: it.name, action: "INVESTIGAR", price: it.price, priceAsOf: it.priceAsOf,
      businessQuality: bq, relative: rel, valuationLine: "", centralUpside: null,
      suggestedAmountUsd: null, suggestedTargetWeight: null,
      evidenceForBuyingNow: [], missing: [], whatWouldChange: [], concentration: "",
      confidence: "baja", priority: 0, severity: 0,
    };
    const concStr = it.effectiveWeight != null
      ? `Exposición efectiva actual ${pctS(it.effectiveWeight)} (límite ${pctS(maxWeightAsset)}).`
      : `Peso directo actual ${pctS(it.heldWeight)} (límite ${pctS(maxWeightAsset)}).`;
    base.concentration = concStr;

    // INVESTIGAR: sin valoración, calidad de datos baja o sin precio.
    if (!v || !v.available || v.quality === "baja" || it.price == null) {
      return {
        ...base, action: "INVESTIGAR", confidence: "baja",
        valuationLine: v?.unavailableReason ?? (v && v.quality === "baja" ? "Valoración de calidad baja (datos débiles o antiguos)." : "Sin valoración fundamental."),
        missing: [v && !v.available ? (v.unavailableReason ?? "fundamentales no disponibles") : "fundamentales recientes y de calidad suficiente", "múltiplos históricos / estimaciones para juzgar el precio actual"],
        whatWouldChange: ["Con fundamentales recientes y una valoración defendible pasaría a COMPRAR o ESPERAR."],
        severity: 20 + (it.composite ?? 0) / 20,
      };
    }

    const central = v.scenarios.find((s) => s.key === "central")!;
    const cons = v.scenarios.find((s) => s.key === "conservador")!;
    base.centralUpside = central.upside;
    base.valuationLine = `Valor razonable central ${central.fairValue.toFixed(2)} (${central.upside >= 0 ? "+" : ""}${pctS(central.upside)} vs precio); conservador ${pctS(cons.upside)}. Calidad ${v.quality}.`;
    const favorable = central.upside >= BUY_UPSIDE && cons.upside > 0 && v.quality === "alta";
    const room = it.heldWeight < maxWeightAsset && (it.effectiveWeight == null || it.effectiveWeight < maxWeightAsset);

    if (favorable && room) {
      return {
        ...base, action: "COMPRAR", confidence: "media",
        suggestedTargetWeight: Math.min(maxWeightAsset, it.heldWeight + 0.05),
        evidenceForBuyingNow: [
          `El crecimiento reportado justifica un descuento al precio actual: central ${pctS(central.upside)}, y aun el conservador es positivo (${pctS(cons.upside)}).`,
          `Calidad del negocio: ${bq} (ROE ${it.roe != null ? pctS(it.roe) : "n/d"}, margen ${it.netMargin != null ? pctS(it.netMargin) : "n/d"}).`,
          "El score es solo contexto; la decisión la sostiene la valoración, no el ranking.",
        ],
        missing: ["Múltiplos históricos y P/E forward para confirmar que no es solo crecimiento extrapolado (modelo EPS×P/E preliminar)."],
        whatWouldChange: [`Deja de ser COMPRAR si el descuento central cae por debajo de ${pctS(BUY_UPSIDE)}, el conservador se vuelve negativo, o rompe tu límite de concentración.`],
        severity: 100 + central.upside * 80,
      };
    }

    // ESPERAR: negocio puede ser bueno, pero la valoración al precio de hoy no da margen.
    return {
      ...base, action: "ESPERAR", confidence: "media",
      evidenceForBuyingNow: [],
      valuationLine: base.valuationLine + (bq === "buena" ? " Buena empresa, pero el precio actual no ofrece margen suficiente." : ""),
      missing: central.upside < BUY_UPSIDE ? ["Un precio más bajo o mejores fundamentales para abrir margen de seguridad."] : ["El conservador no es positivo: el riesgo-retorno no justifica comprar hoy."],
      whatWouldChange: [`Pasaría a COMPRAR si el descuento central supera ${pctS(BUY_UPSIDE)} con conservador positivo (p. ej. tras una corrección de precio o mejora de resultados).`],
      severity: 50 + (it.composite ?? 0) / 10,
    };
  });

  // Montos SOLO para COMPRAR, por CONVICCIÓN (magnitud del descuento central) +
  // tope de concentración; sin reparto igual ni despliegue forzado. La fracción de
  // la liquidez comprometida en un nombre crece con su descuento (tope 60%), de modo
  // que una sola compra modesta NO absorbe todo el presupuesto. El sobrante queda en
  // liquidez (mantenerla es una alternativa válida).
  const CONV_CAP = 0.6;
  const buys = out.filter((d) => d.action === "COMPRAR" && d.centralUpside != null);
  let deployed = 0;
  if (cashAvailable > 0 && buys.length > 0) {
    const raw = buys.map((d) => ({ d, want: cashAvailable * Math.min(CONV_CAP, Math.max(0, d.centralUpside ?? 0)) }));
    const sumWant = raw.reduce((s, r) => s + r.want, 0);
    const scale = sumWant > cashAvailable ? cashAvailable / sumWant : 1;   // nunca exceder la liquidez
    for (const { d, want } of raw) {
      const heldVal = (items.find((i) => i.ticker === d.ticker)?.heldWeight ?? 0) * portfolioValue;
      const roomUsd = Math.max(0, maxWeightAsset * denom - heldVal);
      const amount = Math.max(0, Math.min(want * scale, roomUsd));
      d.suggestedAmountUsd = Math.round(amount);
      deployed += d.suggestedAmountUsd;
    }
  }
  const cashKept = Math.max(0, Math.round(cashAvailable - deployed));

  out.sort((a, b) => b.severity - a.severity);
  const ranked = out.map((d, i) => ({ ...d, priority: i + 1 }));
  const nBuy = buys.length;
  const note = nBuy === 0
    ? `Hoy ninguna candidata cumple el criterio de COMPRAR (valoración favorable con calidad suficiente). Mantener la liquidez (${Math.round(cashAvailable).toLocaleString("en-US")} USD) es una decisión válida; revisa ESPERAR/INVESTIGAR abajo.`
    : `${nBuy} candidata(s) con evidencia de compra hoy: ${deployed.toLocaleString("en-US")} USD por convicción; ${cashKept.toLocaleString("en-US")} USD quedan en liquidez (no se fuerza el presupuesto).`;
  return { decisions: ranked, cashAvailable, deployed, cashKept, note };
}
