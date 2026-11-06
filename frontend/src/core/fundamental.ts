// Motor de VALORACIÓN FUNDAMENTAL por empresa — independiente del motor estadístico
// de riesgo (forecast.ts). Estima el valor económico razonable bajo escenarios con
// SUPUESTOS EXPLÍCITOS, nunca probabilidades ni objetivos garantizados.
//
// Disciplina (roadmap Fase 2 y Fase 10):
//  - No inventa estimaciones de analistas: el crecimiento proviene de los datos
//    reportados (EDGAR) y se etiqueta como SUPUESTO del usuario, no consenso.
//  - El múltiplo central es el P/E TTM ACTUAL de CADA empresa (no el mismo para todas);
//    los escenarios aplican compresión/expansión explícitas.
//  - Si no hay datos suficientes -> "proyección fundamental no disponible" con motivo.
//  - Escenarios ≠ percentiles probabilísticos. Horizonte 12 meses (no extrapolable a 1m).

import type { FundamentalsPayload } from "./valuation";

export type ValMethod = "pe_eps" | "fcf_fallback";

export interface FundamentalInput {
  ticker: string;
  name: string | null;
  sector: string | null;
  price: number | null;
  priceAsOf: string | null;
  f: FundamentalsPayload | undefined;
}

export interface FundScenario {
  key: "conservador" | "central" | "favorable";
  label: string;
  fairValue: number;      // valor razonable por acción (USD)
  upside: number;         // fairValue / price - 1
  assumptions: string[];  // supuestos explícitos de ESTE escenario
}

export interface SensitivityPoint { label: string; fairValue: number; upside: number; }

export interface CompanyValuation {
  ticker: string;
  name: string | null;
  sector: string | null;
  price: number | null;
  priceAsOf: string | null;
  available: boolean;
  method: ValMethod | null;
  horizonLabel: string;
  epsTtm: number | null;
  peUsed: number | null;
  growthCentral: number | null;
  scenarios: FundScenario[];
  sensitivity: SensitivityPoint[];
  quality: "alta" | "media" | "baja";
  dataSources: string[];
  limitations: string[];
  unavailableReason: string | null;
  // --- SEÑALES DESCRIPTIVAS (no circulares, NO son valoración ni decisión) ---
  epsReported: number | null;      // EPS reportado (USD/ADR, último ejercicio anual)
  earningsBasis: "reported_annual" | "ttm" | "normalized" | "forward" | null;  // base del EPS usado
  ttmEps: number | null;           // (arquitectura) EPS TTM — pendiente de proveedor
  normalizedEps: number | null;    // (arquitectura) EPS normalizado/through-cycle — pendiente
  forwardEps: number | null;       // (arquitectura) EPS forward (consenso) — pendiente
  earningsYield: number | null;    // EPS reportado / precio actual (descriptivo)
  fcfYield: number | null;         // FCF / market cap (reportado, descriptivo)
  referenceYield: number;          // rendimiento de referencia DESCRIPTIVO (no umbral de decisión)
  yieldVsReference: "encima" | "cerca" | "debajo" | "n/d";  // posición vs referencia; NO implica cara/barata
  cyclicalAlert: boolean;          // ALERTA de posible ciclicidad/efecto extraordinario (no prueba de pico)
  cyclicalNote: string | null;
  epsConsistent: boolean | null;   // identidad EPS×acciones≈utilidad neta (coherencia moneda/ADR)
  consistencyNotes: string[];
  priceAnchored: boolean;          // los escenarios se anclan al precio/múltiplo actual (circular)
  decisionReady: boolean;          // ¿hay valoración FUNDADA para decidir? (hoy false)
  decisionBlock: string | null;    // por qué no hay decisión de inversión todavía
  decisionBasis: string;           // marco: señal preliminar ≠ recomendación validada
}

// --- Agregación a nivel cartera (Fase 3) -------------------------------------
// Suma por ESCENARIO COHERENTE (todas las empresas en su mismo escenario), no
// suma de medianas individuales. La parte sin valoración fundamental se mantiene
// a valor de mercado ACTUAL (no se proyecta ni se extrapola la cobertura al 100%).
export interface AggItem { marketValue: number; price: number; scenarios: FundScenario[]; }
export interface PortfolioAgg {
  totalCurrent: number;
  coveredCurrent: number;
  uncoveredCurrent: number;
  coveragePct: number;
  perScenario: { key: FundScenario["key"]; label: string; value: number; upside: number }[];
  sensitivityUncovered: { label: string; value: number; upside: number }[];
}

export function aggregateFundamental(covered: AggItem[], uncoveredCurrent: number): PortfolioAgg {
  const coveredCurrent = covered.reduce((s, it) => s + it.marketValue, 0);
  const totalCurrent = coveredCurrent + uncoveredCurrent;
  const keys: FundScenario["key"][] = ["conservador", "central", "favorable"];
  const label = (k: FundScenario["key"]) => k === "conservador" ? "Conservador" : k === "central" ? "Central" : "Favorable";
  const projectedCovered = (k: FundScenario["key"]) =>
    covered.reduce((s, it) => {
      const sc = it.scenarios.find((x) => x.key === k);
      // valor proyectado de la posición = valor de mercado × (valor razonable / precio)
      const factor = sc && it.price > 0 ? sc.fairValue / it.price : 1;
      return s + it.marketValue * factor;
    }, 0);
  const perScenario = keys.map((k) => {
    const value = projectedCovered(k) + uncoveredCurrent;
    return { key: k, label: label(k), value, upside: totalCurrent > 0 ? value / totalCurrent - 1 : 0 };
  });
  // Sensibilidad del consolidado central a la parte NO cubierta (±10%).
  const centralCovered = projectedCovered("central");
  const sensitivityUncovered = [
    { label: "No cubierto −10%", mult: 0.9 },
    { label: "No cubierto +10%", mult: 1.1 },
  ].map((s) => {
    const value = centralCovered + uncoveredCurrent * s.mult;
    return { label: s.label, value, upside: totalCurrent > 0 ? value / totalCurrent - 1 : 0 };
  });
  return {
    totalCurrent, coveredCurrent, uncoveredCurrent,
    coveragePct: totalCurrent > 0 ? coveredCurrent / totalCurrent : 0,
    perScenario, sensitivityUncovered,
  };
}

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
const FINANCIAL_SECTORS = ["financ", "bank", "insur", "seguro"];

// Antigüedad (en días) entre la fecha del ejercicio y la fecha de referencia (precio).
function ageDays(asOf?: string | null, ref?: string | null): number | null {
  if (!asOf || !ref) return null;
  const a = Date.parse(asOf), b = Date.parse(ref);
  if (isNaN(a) || isNaN(b)) return null;
  return Math.round((b - a) / 86400000);
}
const STALE_SOFT = 400;   // ~13 meses: deja de ser "alta" calidad
const STALE_HARD = 550;   // ~18 meses: calidad baja (no apto para decisiones fuertes)

// Bandas de escenario (supuestos explícitos, no pronósticos):
const GROWTH_STEP = 0.05;   // ±5 pp de crecimiento anual de EPS
const PE_COMPRESS = 0.80;   // conservador: múltiplo -20%
const PE_EXPAND = 1.15;     // favorable: múltiplo +15%
const GROWTH_FLOOR = -0.15, GROWTH_CAP = 0.35;

// SEÑAL DESCRIPTIVA (no decisión): el rendimiento de beneficios/FCF reportado se
// compara con un rendimiento de REFERENCIA sólo para situarlo, NUNCA para etiquetar
// la acción como cara o barata (eso exige crecimiento, riesgo, calidad y sector).
const REFERENCE_YIELD = 0.07;            // referencia descriptiva visible (no umbral de decisión)
const REFERENCE_BAND = 0.15;            // ±15% alrededor de la referencia = "cerca"
const CYCLICAL_GROWTH_ABS = 0.75;        // |crec. EPS YoY| ≥ 75% ⇒ ALERTA de ciclicidad/efecto extraordinario
const DECISION_BASIS =
  "Señal PRELIMINAR descriptiva sobre datos limitados (EDGAR, último ejercicio anual). " +
  "NO es valoración, ni recomendación, ni base para decidir compra/venta.";
const DECISION_BLOCK =
  "Sin valoración fundada: faltan beneficios TTM, estimaciones forward, múltiplos históricos " +
  "y beneficios normalizados/through-cycle. Hasta integrarlos, el motor sólo describe señales.";

export function valuateCompany(input: FundamentalInput): CompanyValuation {
  const { ticker, name, sector, price, priceAsOf, f } = input;
  const base: CompanyValuation = {
    ticker, name, sector, price, priceAsOf,
    available: false, method: null, horizonLabel: "12 meses",
    epsTtm: null, peUsed: null, growthCentral: null,
    scenarios: [], sensitivity: [], quality: "baja",
    dataSources: [], limitations: [], unavailableReason: null,
    epsReported: null, earningsBasis: null, ttmEps: null, normalizedEps: null, forwardEps: null,
    earningsYield: null, fcfYield: null, referenceYield: REFERENCE_YIELD, yieldVsReference: "n/d",
    cyclicalAlert: false, cyclicalNote: null, epsConsistent: null, consistencyNotes: [],
    priceAnchored: true, decisionReady: false, decisionBlock: DECISION_BLOCK, decisionBasis: DECISION_BASIS,
  };

  if (price == null || price <= 0) {
    return { ...base, unavailableReason: "Sin precio actual para anclar la valoración." };
  }
  if (!f) {
    return {
      ...base,
      unavailableReason: "Sin fundamentales en la cobertura actual (EDGAR us-gaap). Causa típica: emisor extranjero que presenta 20-F bajo IFRS (p. ej. ASML, TSM), fuera del taxonomy us-gaap. Soporte de ingesta IFRS/20-F en preparación; la posición NO se excluye del análisis.",
      limitations: ["La ausencia de valoración fundamental no implica ausencia de posición: sigue contando en riesgo, exposición y cartera."],
    };
  }

  const isFinancial = sector != null && FINANCIAL_SECTORS.some((k) => sector.toLowerCase().includes(k));
  const srcPrice = `Precio ${price.toFixed(2)} USD (cotización del día)${priceAsOf ? ` al ${priceAsOf}` : ""}.`;
  const prov = `${f.taxonomy ?? "companyfacts"}${f.currency ? `, ${f.currency}` : ""}${f.as_of ? `, ejercicio al ${f.as_of}` : ""}`;
  const srcFund = `Fundamentales SEC EDGAR (${prov}) vía el scan.`;

  // Crecimiento central: EPS YoY si existe, si no ingresos YoY; acotado y etiquetado como ruidoso.
  let g: number | null = null;
  let gNote = "";
  if (f.eps_growth_yoy != null && isFinite(f.eps_growth_yoy)) {
    g = clamp(f.eps_growth_yoy, GROWTH_FLOOR, GROWTH_CAP);
    gNote = `crecimiento de EPS ${(g * 100).toFixed(0)}%/año (histórico interanual, acotado; dato ruidoso de 1 año)`;
  } else if (f.rev_growth_yoy != null && isFinite(f.rev_growth_yoy)) {
    g = clamp(f.rev_growth_yoy, GROWTH_FLOOR, GROWTH_CAP);
    gNote = `crecimiento de ingresos ${(g * 100).toFixed(0)}%/año como proxy (sin EPS YoY)`;
  } else {
    g = 0;
    gNote = "sin dato de crecimiento: se asume EPS plano (0%)";
  }

  // --- Método primario: EPS futuro × múltiplo razonado ---
  const pe = f.pe_ttm;
  if (pe != null && isFinite(pe) && pe > 0) {
    const eps = price / pe;
    const scen = (key: FundScenario["key"], gS: number, mS: number, extra: string): FundScenario => {
      const fairValue = eps * (1 + gS) * mS;
      return {
        key,
        label: key === "conservador" ? "Conservador" : key === "central" ? "Central" : "Favorable",
        fairValue, upside: fairValue / price - 1,
        assumptions: [
          `EPS último ejercicio${f.as_of ? ` (${f.as_of})` : ""} ${eps.toFixed(2)} → ${(eps * (1 + gS)).toFixed(2)} (${gS >= 0 ? "+" : ""}${(gS * 100).toFixed(0)}% a 12m)`,
          `Múltiplo P/E ${mS.toFixed(1)}× (${extra})`,
        ],
      };
    };
    const gCons = clamp(g - GROWTH_STEP, GROWTH_FLOOR, GROWTH_CAP);
    const gFav = clamp(g + GROWTH_STEP, GROWTH_FLOOR, GROWTH_CAP);
    // ADVERTENCIA de circularidad: el central = eps×(1+g)×pe = precio×(1+g) (el múltiplo se
    // cancela). NO es un valor razonable ni un descuento; es proyectar el crecimiento de EPS
    // sobre el precio de hoy. Conservador/favorable sólo aplican un recorte/expansión de múltiplo
    // sobre esa misma ancla de precio. Se muestran como PROYECCIÓN DE PRECIO a 12m, no valoración.
    const scenarios = [
      scen("conservador", gCons, pe * PE_COMPRESS, `múltiplo −${((1 - PE_COMPRESS) * 100).toFixed(0)}% sobre precio actual`),
      scen("central", g, pe, "= precio actual × (1+crecimiento); múltiplo cancelado (circular)"),
      scen("favorable", gFav, pe * PE_EXPAND, `múltiplo +${((PE_EXPAND - 1) * 100).toFixed(0)}% sobre precio actual`),
    ];
    // Sensibilidad: valor central ante ±5pp de crecimiento y ±10% de múltiplo.
    const sens: SensitivityPoint[] = [
      { label: "Crecimiento −5pp", fairValue: eps * (1 + clamp(g - 0.05, GROWTH_FLOOR, GROWTH_CAP)) * pe, upside: 0 },
      { label: "Crecimiento +5pp", fairValue: eps * (1 + clamp(g + 0.05, GROWTH_FLOOR, GROWTH_CAP)) * pe, upside: 0 },
      { label: "Múltiplo −10%", fairValue: eps * (1 + g) * pe * 0.9, upside: 0 },
      { label: "Múltiplo +10%", fairValue: eps * (1 + g) * pe * 1.1, upside: 0 },
    ].map((s) => ({ ...s, upside: s.fairValue / price - 1 }));

    let quality: CompanyValuation["quality"] =
      f.eps_growth_yoy != null && Math.abs(f.eps_growth_yoy) < 0.5 ? "alta"
      : f.eps_growth_yoy != null || f.rev_growth_yoy != null ? "media" : "baja";

    // Antigüedad del ejercicio: fundamentales viejos NO deben sustentar decisiones fuertes.
    const age = ageDays(f.as_of, priceAsOf);
    const staleMonths = age != null ? Math.round(age / 30) : null;
    if (age != null && age > STALE_HARD) quality = "baja";
    else if (age != null && age > STALE_SOFT && quality === "alta") quality = "media";

    const limitations = [
      `El P/E usa el EPS del último ejercicio anual${f.as_of ? ` (${f.as_of})` : ""}, NO un TTM; con un precio actual, el P/E resultante no es un P/E TTM de hoy.`,
      "El múltiplo central supone que el P/E actual se mantiene: es un supuesto, no un pronóstico.",
      `El crecimiento usa ${gNote} — no son estimaciones de analistas.`,
      "Horizonte 12 meses: no aplicable a 1 mes (no extrapolar un objetivo anual a corto plazo).",
      "Los escenarios no son percentiles ni probabilidades.",
      "Sin cobertura de P/E forward, EV/EBITDA, ROIC ni DCF con datos actuales (pendiente de enriquecer EDGAR).",
    ];
    if (staleMonths != null && age! > STALE_SOFT) {
      limitations.unshift(`Fundamentales con ~${staleMonths} meses de antigüedad (ejercicio ${f.as_of}): ${age! > STALE_HARD ? "calidad degradada a baja; no apto para decisiones fuertes" : "calidad reducida"}. Busca un ejercicio más reciente antes de actuar.`);
    }
    if (isFinancial) limitations.push("Sector financiero: P/E sobre EPS es aproximado; idealmente P/B o modelo específico (pendiente).");
    const fcfCross = f.fcf_yield != null && isFinite(f.fcf_yield)
      ? [`Contraste FCF: rendimiento de flujo de caja libre ${(f.fcf_yield * 100).toFixed(1)}% (contexto, no valoración primaria).`]
      : [];

    // --- SEÑAL DESCRIPTIVA (no circular, NO decisión) ---
    // EPS reportado (anual). earnings_basis = reported_annual; TTM/normalizado/forward pendientes.
    const epsReported = (f.eps != null && isFinite(f.eps)) ? f.eps : (pe > 0 ? price / pe : null);
    const earningsYield = (epsReported != null && price > 0) ? epsReported / price : null;
    const fcfYield = (f.fcf_yield != null && isFinite(f.fcf_yield)) ? f.fcf_yield : null;
    const yld = earningsYield ?? fcfYield;
    // Posición vs referencia — SÓLO descriptiva, NO implica cara/barata (ignora crecimiento, riesgo, calidad, sector).
    const yieldVsReference: CompanyValuation["yieldVsReference"] = yld == null ? "n/d"
      : yld >= REFERENCE_YIELD * (1 + REFERENCE_BAND) ? "encima"
      : yld <= REFERENCE_YIELD * (1 - REFERENCE_BAND) ? "debajo" : "cerca";
    // Variación extrema de EPS = ALERTA de posible ciclicidad/efecto extraordinario (NO prueba de pico).
    const cyclicalAlert = f.eps_growth_yoy != null && Math.abs(f.eps_growth_yoy) >= CYCLICAL_GROWTH_ABS;
    const cyclicalNote = cyclicalAlert
      ? `ALERTA: crecimiento de EPS interanual ${((f.eps_growth_yoy ?? 0) * 100).toFixed(0)}% — posible ciclicidad o efecto extraordinario. Requiere revisar beneficios normalizados antes de interpretar el rendimiento; NO se afirma que estén en un máximo.`
      : null;
    // Consistencia EPS/precio/moneda/ADR (del backend si está disponible).
    const consistencyNotes: string[] = [];
    if (f.eps_consistent === false) consistencyNotes.push(`EPS×acciones no cuadra con la utilidad neta (ratio ${f.eps_check_ratio ?? "n/d"}): posible desajuste de acciones/ADR/periodo — tratar el rendimiento con cautela.`);
    if (f.ni_reconstructed) consistencyNotes.push(`Utilidad neta reconstruida como EPS×acciones diluidas (la etiqueta directa no existía en el período de referencia ${f.as_of ?? ""}); márgenes/ROE derivados de ese valor.`);
    if (f.shares_source && f.shares_source.includes("obsoleta")) consistencyNotes.push(`Acciones vigentes de origen "${f.shares_source}": la portada EDGAR estaba obsoleta; market cap aproximado.`);
    if (f.currency && f.currency !== "USD") consistencyNotes.push(`Fundamentales en ${f.currency} convertidos a USD (EPS por ADR); verificar FX/relación ADR antes de comparar con el precio.`);
    limitations.push(
      `Los escenarios son PROYECCIÓN DE PRECIO a 12m ancladas al precio y múltiplo actuales (circular); NO son valor razonable ni descuento.`,
      `Señal DESCRIPTIVA (no valoración, no decisión): rendimiento de beneficios ${earningsYield != null ? (earningsYield * 100).toFixed(1) + "%" : "n/d"}${fcfYield != null ? ` / FCF ${(fcfYield * 100).toFixed(1)}%` : ""} sobre EPS ANUAL reportado${f.as_of ? ` (${f.as_of})` : ""}. Referencia ${(REFERENCE_YIELD * 100).toFixed(0)}% sólo para situar; NO implica que la acción sea cara o barata (ignora crecimiento, riesgo, calidad y sector).`,
      `Bases de beneficio: se usa ANUAL reportado; TTM, normalizado/through-cycle y forward NO disponibles (pendientes del proveedor). No se mezclan periodos.`,
    );
    if (cyclicalNote) limitations.unshift(cyclicalNote);
    consistencyNotes.forEach((n) => limitations.push(n));

    return {
      ...base, available: true, method: "pe_eps",
      epsTtm: eps, peUsed: pe, growthCentral: g,
      scenarios, sensitivity: sens, quality,
      dataSources: [srcPrice, srcFund, ...fcfCross],
      limitations,
      unavailableReason: null,
      epsReported, earningsBasis: (f.eps_basis as CompanyValuation["earningsBasis"]) ?? "reported_annual",
      ttmEps: null, normalizedEps: null, forwardEps: null,
      earningsYield, fcfYield, referenceYield: REFERENCE_YIELD, yieldVsReference,
      cyclicalAlert, cyclicalNote,
      epsConsistent: f.eps_consistent ?? null, consistencyNotes,
      priceAnchored: true, decisionReady: false, decisionBlock: DECISION_BLOCK, decisionBasis: DECISION_BASIS,
    };
  }

  // --- Fallback: FCF yield (cuando hay pérdidas o sin P/E) ---
  if (f.fcf_yield != null && isFinite(f.fcf_yield) && f.fcf_yield > 0) {
    const y = f.fcf_yield;
    // Valor = precio × (yield actual / yield exigido). yield exigido más alto => menor valor.
    const scenByYield = (key: FundScenario["key"], reqYield: number, note: string): FundScenario => {
      const fairValue = price * (y / reqYield);
      return {
        key, label: key === "conservador" ? "Conservador" : key === "central" ? "Central" : "Favorable",
        fairValue, upside: fairValue / price - 1,
        assumptions: [`Rendimiento FCF exigido ${(reqYield * 100).toFixed(1)}% (actual ${(y * 100).toFixed(1)}%)`, note],
      };
    };
    const scenarios = [
      scenByYield("conservador", y * 1.25, "se exige +25% de rendimiento (múltiplo más bajo)"),
      scenByYield("central", y, "se mantiene el rendimiento FCF actual"),
      scenByYield("favorable", y * 0.85, "se acepta −15% de rendimiento (múltiplo más alto)"),
    ];
    const fcfVsRef: CompanyValuation["yieldVsReference"] =
      y >= REFERENCE_YIELD * (1 + REFERENCE_BAND) ? "encima" : y <= REFERENCE_YIELD * (1 - REFERENCE_BAND) ? "debajo" : "cerca";
    return {
      ...base, available: true, method: "fcf_fallback",
      epsTtm: null, peUsed: null, growthCentral: null,
      scenarios, sensitivity: [], quality: "baja",
      dataSources: [srcPrice, srcFund],
      limitations: [
        "Sin P/E positivo (pérdidas o sin EPS en cobertura): se usa rendimiento FCF como respaldo.",
        "Los escenarios de este método son CIRCULARES respecto al precio (valor = precio × y/y_exigido); calidad baja. Requiere DCF con historial de FCF (pendiente).",
        `Señal DESCRIPTIVA: rendimiento FCF ${(y * 100).toFixed(1)}% vs referencia ${(REFERENCE_YIELD * 100).toFixed(0)}% (${fcfVsRef}). Sin EPS no hay rendimiento de beneficios; NO implica cara/barata.`,
      ],
      unavailableReason: null,
      epsReported: null, earningsBasis: null, ttmEps: null, normalizedEps: null, forwardEps: null,
      earningsYield: null, fcfYield: y, referenceYield: REFERENCE_YIELD, yieldVsReference: fcfVsRef,
      cyclicalAlert: false, cyclicalNote: null, epsConsistent: f.eps_consistent ?? null, consistencyNotes: [],
      priceAnchored: true, decisionReady: false, decisionBlock: DECISION_BLOCK, decisionBasis: DECISION_BASIS,
    };
  }

  const hasRatios = f.roe != null || f.net_margin != null || f.eps_growth_yoy != null;
  const foreignNoFx = f.currency != null && f.currency !== "USD";
  let reason: string;
  if (foreignNoFx && hasRatios) {
    reason = `Hay fundamentales en ${f.currency} (${prov}) — ROE, márgenes y crecimientos sí disponibles en Research — pero P/E y FCF en USD requieren conversión FX ${f.currency}→USD, no disponible gratis. Valoración por múltiplos en USD: no disponible.`;
  } else if (pe != null && pe <= 0) {
    reason = "P/E no válido (la empresa reporta pérdidas) y sin rendimiento FCF: valoración por múltiplos no aplicable con los datos actuales.";
  } else {
    reason = "Fundamentales insuficientes (sin P/E TTM ni rendimiento FCF) para una valoración defendible.";
  }
  return { ...base, unavailableReason: reason };
}
