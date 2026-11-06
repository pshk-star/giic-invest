// Revisión POR POSICIÓN de la cartera actual (Investment Advisor, Fase 5).
// Integra: valoración fundamental (preliminar), exposición efectiva vía ETFs,
// contribución al riesgo (covarianzas) y CALIDAD DE DATOS.
//
// Disciplina (puntos del usuario):
//  - NO recortar/vender SOLO por concentración ni comprar SOLO por score.
//    Cada acción fuerte exige evidencia CONVERGENTE (valoración + riesgo/exposición).
//  - El modelo EPS×P/E es PRELIMINAR: no se usa como base única de decisiones fuertes.
//  - Sin evidencia suficiente -> MANTENER o REVISAR (resultados válidos).

import type { CompanyValuation, FundScenario } from "./fundamental";

export type PosKind = "equity" | "etf" | "commodity";
export type PosAction = "AUMENTAR" | "MANTENER" | "REDUCIR" | "VENDER" | "REVISAR";

export interface PositionReviewInput {
  ticker: string;
  name: string | null;
  sector: string | null;
  kind: PosKind;
  price: number | null;
  priceAsOf: string | null;
  marketValue: number;
  weight: number;                   // peso directo (fracción de la cartera total)
  effectiveWeight: number | null;   // exposición efectiva total (directa + vía ETFs); null si no se pudo calcular
  riskPct: number | null;           // contribución al riesgo (0-1); null si no hay modelo
  valuation: CompanyValuation | null;  // solo acciones
  totalValue: number;               // valor total de la cartera (para montos)
  maxWeightAsset: number;
  maxWeightSector: number;
  sectorWeight: number | null;      // peso efectivo del sector (contexto)
}

export interface PositionReview {
  ticker: string;
  name: string | null;
  kind: PosKind;
  action: PosAction;
  price: number | null;
  priceAsOf: string | null;
  weight: number;
  effectiveWeight: number | null;
  targetWeight: number | null;
  amountUsd: number | null;         // compra(+)/venta(−) aproximada
  valuationLine: string;
  scenarios: FundScenario[] | null;
  rationale: string[];
  risks: string[];
  whatInvalidates: string[];
  beforeAfter: string;
  evidenceQuality: "alta" | "media" | "baja";
  priority: number;
  severity: number;
}

const CHEAP = 0.15;     // upside central ≥ +15%
const RICH = -0.10;     // upside central ≤ −10%
const HIGH_RISK = 0.45; // contribución al riesgo dominante
const pctS = (x: number) => `${(x * 100).toFixed(1)}%`;
const PRELIM = "El modelo de valoración (EPS×P/E) es preliminar: múltiplo actual y bandas ±20% son supuestos, no un valor justo validado; no es base única para decisiones fuertes.";

function reviewEquity(it: PositionReviewInput): PositionReview {
  const v = it.valuation;
  const effStr = it.effectiveWeight != null
    ? `Exposición efectiva total ${pctS(it.effectiveWeight)}${it.effectiveWeight > it.weight + 1e-4 ? ` (directa ${pctS(it.weight)} + vía ETFs)` : ""}.`
    : "Exposición efectiva vía ETFs no calculada.";
  const riskStr = it.riskPct != null ? `Contribución al riesgo ${pctS(it.riskPct)}.` : "Sin modelo de riesgo.";
  const base: PositionReview = {
    ticker: it.ticker, name: it.name, kind: "equity", action: "MANTENER",
    price: it.price, priceAsOf: it.priceAsOf, weight: it.weight, effectiveWeight: it.effectiveWeight,
    targetWeight: null, amountUsd: null, valuationLine: "", scenarios: v?.scenarios ?? null,
    rationale: [], risks: [], whatInvalidates: [], beforeAfter: "", evidenceQuality: "media",
    priority: 0, severity: 0,
  };

  // Sin valoración (p. ej. emisor extranjero 20-F) -> REVISAR, nunca excluir.
  if (!v || !v.available) {
    return {
      ...base, action: "REVISAR", evidenceQuality: "baja",
      valuationLine: v?.unavailableReason ?? "Valoración fundamental no disponible.",
      rationale: [
        `${effStr} ${riskStr}`,
        v?.unavailableReason ?? "Sin fundamentales para una valoración defendible.",
        "Se marca REVISAR (no se excluye del análisis ni se recomienda a ciegas).",
      ],
      risks: ["Decidir sin valoración fundamental sube el riesgo de error."],
      whatInvalidates: ["Habrá acción cuando exista cobertura de fundamentales (p. ej. soporte IFRS/20-F)."],
      beforeAfter: "Sin cambios propuestos.",
      severity: 50 + it.weight * 40,
    };
  }

  const central = v.scenarios.find((s) => s.key === "central")!;
  const cons = v.scenarios.find((s) => s.key === "conservador")!;
  const fav = v.scenarios.find((s) => s.key === "favorable")!;
  const cheap = central.upside >= CHEAP && cons.upside > -0.05;
  const rich = central.upside <= RICH && fav.upside < 0.05;
  const overW = it.weight > it.maxWeightAsset;
  const overEff = it.effectiveWeight != null && it.effectiveWeight > it.maxWeightAsset;
  const highRisk = it.riskPct != null && it.riskPct > HIGH_RISK;
  const concentrated = overW || overEff || highRisk;
  const q = v.quality;

  base.valuationLine = `Valor razonable central ${central.fairValue.toFixed(2)} USD (${central.upside >= 0 ? "+" : ""}${pctS(central.upside)} vs precio). Calidad de datos: ${q}.`;
  const commonRisks = [PRELIM];
  const commonInval = ["Cambia si se actualizan los fundamentales o el precio se mueve materialmente."];

  // Calidad baja -> REVISAR (no decisiones fuertes con datos débiles, punto 1).
  if (q === "baja") {
    return {
      ...base, action: "REVISAR", evidenceQuality: "baja",
      rationale: [`${effStr} ${riskStr}`, "Calidad de datos baja: no se emite acción fuerte.", PRELIM],
      risks: commonRisks, whatInvalidates: commonInval, beforeAfter: "Sin cambios propuestos.",
      severity: 40 + it.weight * 30,
    };
  }

  // VENDER: sobrevaloración clara + corroboración de riesgo/concentración + datos de alta calidad.
  if (rich && concentrated && q === "alta") {
    const amount = -it.marketValue;
    return {
      ...base, action: "VENDER", evidenceQuality: "alta",
      targetWeight: 0, amountUsd: Math.round(amount),
      rationale: [
        `Valoración exigente: central ${pctS(central.upside)} y aún el favorable (${pctS(fav.upside)}) ofrece poco.`,
        `Corroborado por ${overW || overEff ? "concentración" : "riesgo"}: ${effStr} ${riskStr}`,
        "Evidencia convergente (valoración + riesgo), no una sola señal.",
      ],
      risks: [...commonRisks, "Vender genera impuestos/costos y renuncia al upside si ejecuta mejor de lo supuesto."],
      whatInvalidates: [...commonInval, "No aplica si el crecimiento futuro supera el supuesto conservador."],
      beforeAfter: `Liberaría ${pctS(it.weight)} de peso directo${it.riskPct != null ? ` y ${pctS(it.riskPct)} del riesgo` : ""}.`,
      severity: 100 + it.weight * 60,
    };
  }

  // REDUCIR: concentración/riesgo + valoración NO barata (gestión de riesgo, nunca solo concentración).
  if (concentrated && !cheap) {
    const cap = it.maxWeightAsset;
    const targetVal = cap * it.totalValue;
    const amount = Math.min(0, targetVal - it.marketValue);
    return {
      ...base, action: "REDUCIR", evidenceQuality: q,
      targetWeight: cap, amountUsd: Math.round(amount),
      rationale: [
        overW ? `Peso directo ${pctS(it.weight)} > límite ${pctS(cap)}.` : overEff ? `Exposición efectiva ${pctS(it.effectiveWeight!)} > límite ${pctS(cap)} (${effStr}).` : `${riskStr} supera el umbral de concentración de riesgo.`,
        `La valoración NO es barata (central ${pctS(central.upside)}), así que recortar no sacrifica un descuento claro.`,
        "Es gestión de riesgo, reversible; no es un juicio de que la empresa sea mala.",
      ],
      risks: [...commonRisks, "Recortar un ganador reduce el upside si sigue subiendo; considera impuestos/costos."],
      whatInvalidates: [...commonInval, `No aplica si bajas por debajo del límite o si la valoración pasa a barata.`],
      beforeAfter: `Llevaría el peso directo de ${pctS(it.weight)} a ${pctS(cap)}${it.riskPct != null ? `; reduce su ${pctS(it.riskPct)} de aporte al riesgo` : ""}.`,
      severity: (highRisk ? 90 : 78) + it.weight * 50,
    };
  }

  // AUMENTAR: barata + con espacio + alta calidad (con la advertencia de modelo preliminar).
  if (cheap && !concentrated && q === "alta" && it.weight < it.maxWeightAsset) {
    const target = Math.min(it.maxWeightAsset, it.weight + 0.05);
    const amount = Math.max(0, (target - it.weight) * it.totalValue);
    return {
      ...base, action: "AUMENTAR", evidenceQuality: "media",
      targetWeight: target, amountUsd: Math.round(amount),
      rationale: [
        `Descuento en el escenario central (${pctS(central.upside)}) y el conservador no es muy negativo (${pctS(cons.upside)}).`,
        `Hay espacio bajo tu límite por activo (${effStr}).`,
        "Aumento modesto (hasta +5pp); NO se dimensiona por un score.",
      ],
      risks: [...commonRisks, "Un solo modelo preliminar no justifica una apuesta grande; escalona la entrada."],
      whatInvalidates: [...commonInval, "No aplica si el descuento desaparece o rompe tu límite por activo/sector."],
      beforeAfter: `Subiría el peso directo de ${pctS(it.weight)} a ${pctS(target)}.`,
      severity: 60 + central.upside * 40 + it.weight * 20,
    };
  }

  // MANTENER por defecto.
  return {
    ...base, action: "MANTENER", evidenceQuality: q,
    rationale: [
      `Dentro de límites y sin señal convergente para actuar (central ${pctS(central.upside)}).`,
      `${effStr} ${riskStr}`,
      cheap ? "Parece barata pero ya tiene peso adecuado o faltan condiciones para aumentar con convicción." : "Valoración y riesgo no piden cambios hoy.",
    ],
    risks: commonRisks, whatInvalidates: commonInval,
    beforeAfter: "Sin cambios propuestos.",
    severity: 20 + it.weight * 20,
  };
}

function reviewNonEquity(it: PositionReviewInput): PositionReview {
  const isCommodity = it.kind === "commodity";
  const overW = it.weight > it.maxWeightAsset;
  const highRisk = it.riskPct != null && it.riskPct > HIGH_RISK;
  const action: PosAction = overW || highRisk ? "REVISAR" : "MANTENER";
  const kindLabel = isCommodity ? "Materia prima (oro/plata): sin fundamentales de empresa." : "ETF: exposición diversificada; valoración look-through de sus subyacentes pendiente (Fase 3).";
  return {
    ticker: it.ticker, name: it.name, kind: it.kind, action,
    price: it.price, priceAsOf: it.priceAsOf, weight: it.weight, effectiveWeight: it.effectiveWeight,
    targetWeight: null, amountUsd: null,
    valuationLine: kindLabel,
    scenarios: null,
    rationale: [
      kindLabel,
      it.riskPct != null ? `Peso ${pctS(it.weight)}; contribución al riesgo ${pctS(it.riskPct)}.` : `Peso ${pctS(it.weight)}.`,
      action === "REVISAR"
        ? "Peso o riesgo elevados: conviene revisar su rol (solapamiento/diversificación), no vender automáticamente."
        : "Cumple rol diversificador; sin acción hoy.",
    ],
    risks: isCommodity ? ["Las materias primas no generan flujo; su valor depende del precio spot."] : ["Posible solapamiento con otras posiciones (ver X-Ray)."],
    whatInvalidates: ["Cambiaría con un rebalanceo global o si su solapamiento sube materialmente."],
    beforeAfter: "Sin cambios propuestos.",
    evidenceQuality: isCommodity ? "media" : "media",
    priority: 0,
    severity: (action === "REVISAR" ? 45 : 18) + it.weight * 20,
  };
}

export function reviewPositions(items: PositionReviewInput[]): PositionReview[] {
  const out = items.map((it) => (it.kind === "equity" ? reviewEquity(it) : reviewNonEquity(it)));
  out.sort((a, b) => b.severity - a.severity);
  return out.map((d, i) => ({ ...d, priority: i + 1 }));
}
