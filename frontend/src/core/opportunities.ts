// Motor de OPORTUNIDADES (¿qué comprar HOY?) — criterio financiero, no por score.
//
// Reglas (puntos del usuario + auditoría de circularidad):
//  - Un score alto del scanner NO activa COMPRAR por sí solo (es atractivo relativo).
//  - COMPRAR se decide por la señal de valor NO circular del núcleo (rendimiento de
//    beneficios/FCF reportado vs un retorno exigido explícito), con calidad alta, sin
//    beneficio cíclico/extraordinario y con espacio de concentración. El crecimiento
//    proyectado (EPS×P/E con múltiplo constante) es CIRCULAR y sólo se muestra como contexto.
//  - ESPERAR = hay datos pero el rendimiento no es atractivo, es cíclico o la calidad no es alta.
//    INVESTIGAR = brecha de DATOS (sin EPS/PE, sin precio, ejercicio muy antiguo) — NO veredicto.
//  - Montos por CONVICCIÓN (exceso del rendimiento sobre el exigido) + tope de concentración,
//    NUNCA reparto igual ni despliegue forzado. Mantener liquidez es válido.
//  - Distingue: buena empresa / atractivo relativo / oportunidad real al precio de hoy.
//  - No usa A/B/C. No inventa valoraciones ni márgenes de seguridad. La decisión del motor
//    NO es una recomendación financiera validada.

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

const REQUIRED_RETURN_FALLBACK = 0.07;   // debe coincidir con fundamental.ts
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

    // INVESTIGAR: brecha de DATOS, no veredicto de inversión. Una buena empresa puede caer aquí
    // sólo porque el proveedor no expuso su EPS o el ejercicio es muy antiguo.
    if (!v || !v.available || v.quality === "baja" || it.price == null) {
      const gapReason = it.price == null ? "sin precio actual"
        : !v || !v.available ? (v?.unavailableReason ?? "sin fundamentales en cobertura")
        : "ejercicio demasiado antiguo o datos insuficientes (calidad baja)";
      return {
        ...base, action: "INVESTIGAR", confidence: "baja",
        valuationLine: `Brecha de datos (${gapReason}). Esto NO significa que la inversión sea poco atractiva: significa que faltan datos para juzgar el precio actual.`,
        missing: [
          "EPS reportado y/o P/E utilizable, o un ejercicio más reciente.",
          "Una fuente de valor independiente del precio (múltiplos históricos, estimaciones forward, FCF/DCF con beneficios normalizados).",
        ],
        whatWouldChange: ["Con datos recientes y una señal de valor independiente pasaría a COMPRAR o ESPERAR; hasta entonces no se emite veredicto."],
        severity: 20 + (it.composite ?? 0) / 20,
      };
    }

    // Señal de valor NO circular (del núcleo): rendimiento de beneficios/FCF vs retorno exigido.
    const central = v.scenarios.find((s) => s.key === "central");
    base.centralUpside = central ? central.upside : null;   // SOLO contexto: proyección 12m circular
    const yld = v.earningsYield ?? v.fcfYield;
    const yldStr = v.earningsYield != null ? `rend. beneficios ${pctS(v.earningsYield)}`
      : v.fcfYield != null ? `rend. FCF ${pctS(v.fcfYield)}` : "rend. n/d";
    base.valuationLine =
      `Señal de valor (no circular): ${yldStr} vs exigido ${pctS(v.requiredReturn)} → ${v.yieldVerdict}. ` +
      `Calidad de datos ${v.quality}${v.cyclical ? "; beneficio potencialmente cíclico/extraordinario" : ""}. ` +
      `(Proyección 12m manteniendo múltiplo: ${central && central.upside >= 0 ? "+" : ""}${central ? pctS(central.upside) : "n/d"} — circular, sólo contexto.)`;

    const room = it.heldWeight < maxWeightAsset && (it.effectiveWeight == null || it.effectiveWeight < maxWeightAsset);
    // COMPRAR exige señal de valor NO circular atractiva + calidad alta + no cíclico + espacio.
    // El crecimiento acotado (proyección circular) NO dispara COMPRAR.
    const favorable = v.yieldVerdict === "atractivo" && v.quality === "alta" && !v.cyclical;

    if (favorable && room) {
      return {
        ...base, action: "COMPRAR", confidence: "media",
        suggestedTargetWeight: Math.min(maxWeightAsset, it.heldWeight + 0.05),
        evidenceForBuyingNow: [
          `Rendimiento de beneficios reportado (${yldStr}) supera el retorno exigido ${pctS(v.requiredReturn)} con margen — señal independiente del precio, no un múltiplo extrapolado.`,
          `Calidad del negocio: ${bq} (ROE ${it.roe != null ? pctS(it.roe) : "n/d"}, margen ${it.netMargin != null ? pctS(it.netMargin) : "n/d"}); datos de calidad alta y sin señal de beneficio extraordinario.`,
          "El score y la proyección de precio a 12m son sólo contexto; la decisión la sostiene el rendimiento reportado.",
        ],
        missing: ["Confirmación con beneficios normalizados/through-cycle, múltiplos históricos y estimaciones forward (pendiente de la fuente de datos en evaluación)."],
        whatWouldChange: [`Deja de ser COMPRAR si el rendimiento cae por debajo del exigido, aparece señal cíclica/extraordinaria, la calidad baja, o rompe tu límite de concentración.`],
        severity: 100 + (yld != null ? (yld - v.requiredReturn) * 400 : 0),
      };
    }

    // ESPERAR: hay datos, pero la señal de valor no es atractiva, o es cíclica, o calidad no-alta.
    const whyWait = v.cyclical ? "beneficio potencialmente cíclico/extraordinario: el rendimiento actual puede no ser sostenible"
      : v.yieldVerdict === "caro" ? "el rendimiento de beneficios está por debajo del retorno exigido (caro sobre beneficios actuales)"
      : v.yieldVerdict === "razonable" ? "el rendimiento iguala pero no supera el retorno exigido: sin margen"
      : v.quality !== "alta" ? "la calidad de datos no es alta (ejercicio antiguo o crecimiento ruidoso)"
      : "sin señal de valor suficiente al precio actual";
    return {
      ...base, action: "ESPERAR", confidence: "media",
      evidenceForBuyingNow: [],
      valuationLine: base.valuationLine + (bq === "buena" ? " Negocio de calidad, pero el precio de hoy no ofrece margen demostrable." : ""),
      missing: [`Para justificar COMPRAR: ${whyWait}. Falta una señal de valor independiente del precio.`],
      whatWouldChange: ["Pasaría a COMPRAR si el rendimiento reportado supera el exigido con margen, con calidad alta y sin señal cíclica (p. ej. tras corrección de precio, mejora sostenible de resultados o datos normalizados)."],
      severity: 50 + (it.composite ?? 0) / 10,
    };
  });

  // Montos SOLO para COMPRAR, por CONVICCIÓN (exceso del rendimiento sobre el exigido) +
  // tope de concentración; sin reparto igual ni despliegue forzado. La fracción de
  // la liquidez comprometida en un nombre crece con su descuento (tope 60%), de modo
  // que una sola compra modesta NO absorbe todo el presupuesto. El sobrante queda en
  // liquidez (mantenerla es una alternativa válida).
  const CONV_CAP = 0.6;
  const buys = out.filter((d) => d.action === "COMPRAR");
  // Convicción = exceso del rendimiento reportado sobre el retorno exigido (señal NO circular),
  // NO el crecimiento proyectado. Mayor exceso ⇒ mayor fracción de liquidez (tope 60%).
  const convOf = (ticker: string): number => {
    const v = items.find((i) => i.ticker === ticker)?.valuation;
    const yld = (v?.earningsYield ?? v?.fcfYield);
    const req = v?.requiredReturn ?? REQUIRED_RETURN_FALLBACK;
    return yld != null && req > 0 ? Math.max(0, (yld - req) / req) : 0;
  };
  let deployed = 0;
  if (cashAvailable > 0 && buys.length > 0) {
    const raw = buys.map((d) => ({ d, want: cashAvailable * Math.min(CONV_CAP, convOf(d.ticker)) }));
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
