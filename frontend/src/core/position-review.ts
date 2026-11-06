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

const HIGH_RISK = 0.45; // contribución al riesgo dominante
const pctS = (x: number) => `${(x * 100).toFixed(1)}%`;
const PRELIM = "La proyección de precio a 12m (EPS×P/E con múltiplo constante) es CIRCULAR y no es valoración. El rendimiento de beneficios/FCF es una señal DESCRIPTIVA (no implica cara/barata). Sin valoración fundada (TTM/forward/múltiplos históricos/normalizada) NO se emiten compras ni ventas por valoración; sólo gestión de riesgo por concentración.";

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

  const central = v.scenarios.find((s) => s.key === "central");
  const yldStr = v.earningsYield != null ? `rend. beneficios ${pctS(v.earningsYield)} (EPS anual)`
    : v.fcfYield != null ? `rend. FCF ${pctS(v.fcfYield)}` : "rend. n/d";
  const overW = it.weight > it.maxWeightAsset;
  const overEff = it.effectiveWeight != null && it.effectiveWeight > it.maxWeightAsset;
  const highRisk = it.riskPct != null && it.riskPct > HIGH_RISK;
  const concentrated = overW || overEff || highRisk;
  const q = v.quality;

  base.valuationLine =
    `Señal DESCRIPTIVA (no decisión): ${yldStr}, ${v.yieldVsReference} de la referencia ${pctS(v.referenceYield)} — NO implica cara/barata. ` +
    `Calidad ${q}${v.cyclicalAlert ? "; ALERTA de ciclicidad/efecto extraordinario" : ""}. ` +
    `(Proyección 12m circular: ${central && central.upside >= 0 ? "+" : ""}${central ? pctS(central.upside) : "n/d"} — sólo contexto.)`;
  const commonRisks = [PRELIM];
  const commonInval = ["Cambia cuando exista valoración fundada (TTM/forward/múltiplos históricos/normalizada) o se actualicen los fundamentales."];

  // REVISAR: datos débiles, ALERTA de ciclicidad, o inconsistencia EPS → requiere revisión humana,
  // nunca una acción de compra/venta por valoración (no la hay).
  if (q === "baja" || v.cyclicalAlert || v.epsConsistent === false) {
    const why = q === "baja" ? "calidad de datos baja"
      : v.cyclicalAlert ? "alerta de ciclicidad/efecto extraordinario (revisar beneficios normalizados)"
      : "posible inconsistencia EPS/acciones/ADR";
    return {
      ...base, action: "REVISAR", evidenceQuality: "baja",
      rationale: [`${effStr} ${riskStr}`, `Requiere revisión (${why}): no se emite acción por valoración.`, PRELIM],
      risks: commonRisks, whatInvalidates: commonInval, beforeAfter: "Sin cambios propuestos.",
      severity: 45 + it.weight * 30,
    };
  }

  // REDUCIR: SÓLO gestión de riesgo por concentración/riesgo (reversible), INDEPENDIENTE de valoración.
  // No se vende por valoración: no existe una valoración fundada para esa decisión.
  if (concentrated) {
    const cap = it.maxWeightAsset;
    const amount = Math.min(0, cap * it.totalValue - it.marketValue);
    return {
      ...base, action: "REDUCIR", evidenceQuality: q,
      targetWeight: cap, amountUsd: Math.round(amount),
      rationale: [
        overW ? `Peso directo ${pctS(it.weight)} > límite ${pctS(cap)}.` : overEff ? `Exposición efectiva ${pctS(it.effectiveWeight!)} > límite ${pctS(cap)} (${effStr}).` : `${riskStr} supera el umbral de concentración de riesgo.`,
        "Gestión de RIESGO (concentración), reversible — NO es un juicio de valoración ni de que la empresa sea mala.",
        "No depende de si está cara o barata: no hay valoración fundada para decidir eso.",
      ],
      risks: [...commonRisks, "Recortar un ganador reduce el recorrido si sigue subiendo; considera impuestos/costos."],
      whatInvalidates: [...commonInval, "No aplica si bajas por debajo del límite."],
      beforeAfter: `Llevaría el peso directo de ${pctS(it.weight)} a ${pctS(cap)}${it.riskPct != null ? `; reduce su ${pctS(it.riskPct)} de aporte al riesgo` : ""}.`,
      severity: (highRisk ? 90 : 78) + it.weight * 50,
    };
  }

  // MANTENER por defecto: hay datos y señales descriptivas, pero NO hay valoración fundada para
  // comprar ni vender. AUMENTAR/VENDER por valoración quedan desactivados hasta integrar mejores datos.
  return {
    ...base, action: "MANTENER", evidenceQuality: q,
    rationale: [
      `Dentro de límites; sin valoración fundada no se decide comprar ni vender (${yldStr}, ${v.yieldVsReference} de la referencia — descriptivo).`,
      `${effStr} ${riskStr}`,
      "Las decisiones por valoración esperan datos fundados (beneficios TTM/normalizados, estimaciones forward, múltiplos históricos).",
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
