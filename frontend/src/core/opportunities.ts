// Motor de SEÑALES de oportunidad (preliminar) — NO decide compras.
//
// Estado (tras degradar la criba a señal descriptiva):
//  - NO se emite COMPRAR: no existe valoración fundada. No se convierte una referencia
//    fija de rendimiento en una decisión de compra/venta (sería tan arbitrario como el 7%).
//  - ESPERAR = EN OBSERVACIÓN: hay datos; se muestra la señal descriptiva (rendimiento de
//    beneficios/FCF, posición vs referencia, alerta de ciclicidad), pero NO es decisión.
//  - INVESTIGAR = brecha de DATOS (sin EPS/PE, sin precio, ejercicio muy antiguo) — NO veredicto.
//  - El rendimiento vs referencia NO implica cara/barata (ignora crecimiento, riesgo, calidad, sector).
//  - La proyección EPS×P/E (múltiplo constante) es CIRCULAR y sólo se muestra como contexto.
//  - Sin montos ni despliegue: la liquidez se conserva íntegra. No usa A/B/C.
//  - Arquitectura lista para decidir cuando lleguen beneficios TTM/normalizados, estimaciones
//    forward y múltiplos históricos (decisionReady en el núcleo de valoración).

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
        whatWouldChange: ["Con datos recientes y una valoración fundada (TTM/forward/múltiplos históricos/normalizada) podría evaluarse una decisión; hasta entonces sólo se describe."],
        severity: 20 + (it.composite ?? 0) / 20,
      };
    }

    // CON DATOS: sólo SEÑAL DESCRIPTIVA (EN OBSERVACIÓN). NO se emite COMPRAR: no existe
    // valoración fundada (el rendimiento vs una referencia fija NO decide cara/barata).
    const central = v.scenarios.find((s) => s.key === "central");
    base.centralUpside = central ? central.upside : null;   // SOLO contexto: proyección 12m circular
    const yldStr = v.earningsYield != null ? `rend. beneficios ${pctS(v.earningsYield)} (EPS anual)`
      : v.fcfYield != null ? `rend. FCF ${pctS(v.fcfYield)}` : "rend. n/d";
    base.valuationLine =
      `Señal DESCRIPTIVA (no decisión): ${yldStr}, ${v.yieldVsReference} de la referencia ${pctS(v.referenceYield)}. ` +
      `No implica cara/barata (ignora crecimiento, riesgo, calidad y sector). ` +
      `Calidad de datos ${v.quality}${v.cyclicalAlert ? "; ALERTA de ciclicidad/efecto extraordinario" : ""}. ` +
      `(Proyección 12m circular: ${central && central.upside >= 0 ? "+" : ""}${central ? pctS(central.upside) : "n/d"} — sólo contexto.)`;

    return {
      ...base, action: "ESPERAR", confidence: "baja",
      evidenceForBuyingNow: [],
      valuationLine: base.valuationLine,
      missing: [
        v.decisionBlock ?? "Sin valoración fundada para decidir compra.",
        ...(v.cyclicalAlert ? ["ALERTA de ciclicidad/efecto extraordinario: revisar beneficios normalizados antes de interpretar el rendimiento."] : []),
        ...v.consistencyNotes,
      ],
      whatWouldChange: ["Habrá decisión cuando exista valoración fundada (beneficios TTM/normalizados, estimaciones forward, múltiplos históricos). Hoy es sólo una señal en observación."],
      severity: 50 + (it.composite ?? 0) / 10 + (v.cyclicalAlert ? 5 : 0),
    };
  });

  // SIN montos: el motor NO emite COMPRAR porque NO hay valoración fundada. No se
  // convierte una referencia fija en una decisión de compra. La liquidez se conserva íntegra.
  const deployed = 0;
  const cashKept = Math.max(0, Math.round(cashAvailable));

  out.sort((a, b) => b.severity - a.severity);
  const ranked = out.map((d, i) => ({ ...d, priority: i + 1 }));
  const nObs = out.filter((d) => d.action === "ESPERAR").length;
  const note =
    `Señales PRELIMINARES, no decisiones de compra. Sin valoración fundada (faltan beneficios ` +
    `TTM/normalizados, estimaciones forward y múltiplos históricos), el motor no emite COMPRAR: ` +
    `${nObs} candidata(s) en observación, el resto en investigación. La liquidez (` +
    `${Math.round(cashAvailable).toLocaleString("en-US")} USD) se mantiene íntegra.`;
  return { decisions: ranked, cashAvailable, deployed, cashKept, note };
}
