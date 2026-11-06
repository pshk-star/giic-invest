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

// Bandas de escenario (supuestos explícitos, no pronósticos):
const GROWTH_STEP = 0.05;   // ±5 pp de crecimiento anual de EPS
const PE_COMPRESS = 0.80;   // conservador: múltiplo -20%
const PE_EXPAND = 1.15;     // favorable: múltiplo +15%
const GROWTH_FLOOR = -0.15, GROWTH_CAP = 0.35;

export function valuateCompany(input: FundamentalInput): CompanyValuation {
  const { ticker, name, sector, price, priceAsOf, f } = input;
  const base: CompanyValuation = {
    ticker, name, sector, price, priceAsOf,
    available: false, method: null, horizonLabel: "12 meses",
    epsTtm: null, peUsed: null, growthCentral: null,
    scenarios: [], sensitivity: [], quality: "baja",
    dataSources: [], limitations: [], unavailableReason: null,
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
  const srcPrice = `Precio ${price.toFixed(2)} USD de price_history (adjclose Yahoo)${priceAsOf ? ` al ${priceAsOf}` : ""}.`;
  const srcFund = "Fundamentales SEC EDGAR (companyfacts) vía el scan diario.";

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
          `EPS TTM ${eps.toFixed(2)} → ${(eps * (1 + gS)).toFixed(2)} (${gS >= 0 ? "+" : ""}${(gS * 100).toFixed(0)}% a 12m)`,
          `Múltiplo P/E ${mS.toFixed(1)}× (${extra})`,
        ],
      };
    };
    const gCons = clamp(g - GROWTH_STEP, GROWTH_FLOOR, GROWTH_CAP);
    const gFav = clamp(g + GROWTH_STEP, GROWTH_FLOOR, GROWTH_CAP);
    const scenarios = [
      scen("conservador", gCons, pe * PE_COMPRESS, `compresión −${((1 - PE_COMPRESS) * 100).toFixed(0)}% vs ${pe.toFixed(1)}× actual`),
      scen("central", g, pe, "se mantiene el P/E actual"),
      scen("favorable", gFav, pe * PE_EXPAND, `expansión +${((PE_EXPAND - 1) * 100).toFixed(0)}% vs ${pe.toFixed(1)}× actual`),
    ];
    // Sensibilidad: valor central ante ±5pp de crecimiento y ±10% de múltiplo.
    const sens: SensitivityPoint[] = [
      { label: "Crecimiento −5pp", fairValue: eps * (1 + clamp(g - 0.05, GROWTH_FLOOR, GROWTH_CAP)) * pe, upside: 0 },
      { label: "Crecimiento +5pp", fairValue: eps * (1 + clamp(g + 0.05, GROWTH_FLOOR, GROWTH_CAP)) * pe, upside: 0 },
      { label: "Múltiplo −10%", fairValue: eps * (1 + g) * pe * 0.9, upside: 0 },
      { label: "Múltiplo +10%", fairValue: eps * (1 + g) * pe * 1.1, upside: 0 },
    ].map((s) => ({ ...s, upside: s.fairValue / price - 1 }));

    const quality: CompanyValuation["quality"] =
      f.eps_growth_yoy != null && Math.abs(f.eps_growth_yoy) < 0.5 ? "alta"
      : f.eps_growth_yoy != null || f.rev_growth_yoy != null ? "media" : "baja";

    const limitations = [
      "El múltiplo central supone que el P/E actual se mantiene: es un supuesto, no un pronóstico.",
      `El crecimiento usa ${gNote} — no son estimaciones de analistas.`,
      "Horizonte 12 meses: no aplicable a 1 mes (no extrapolar un objetivo anual a corto plazo).",
      "Los escenarios no son percentiles ni probabilidades.",
      "Sin cobertura de P/E forward, EV/EBITDA, ROIC ni DCF con datos actuales (pendiente de enriquecer EDGAR).",
    ];
    if (isFinancial) limitations.push("Sector financiero: P/E sobre EPS es aproximado; idealmente P/B o modelo específico (pendiente).");
    const fcfCross = f.fcf_yield != null && isFinite(f.fcf_yield)
      ? [`Contraste FCF: rendimiento de flujo de caja libre ${(f.fcf_yield * 100).toFixed(1)}% (contexto, no valoración primaria).`]
      : [];

    return {
      ...base, available: true, method: "pe_eps",
      epsTtm: eps, peUsed: pe, growthCentral: g,
      scenarios, sensitivity: sens, quality,
      dataSources: [srcPrice, srcFund, ...fcfCross],
      limitations,
      unavailableReason: null,
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
    return {
      ...base, available: true, method: "fcf_fallback",
      epsTtm: null, peUsed: null, growthCentral: null,
      scenarios, sensitivity: [], quality: "baja",
      dataSources: [srcPrice, srcFund],
      limitations: [
        "Sin P/E TTM positivo (pérdidas o sin cobertura): se usa rendimiento FCF como método de respaldo.",
        "Método circular respecto al precio; calidad baja. Requiere DCF con historial de FCF (pendiente).",
        "Escenarios por rendimiento exigido = supuestos explícitos, no probabilidades.",
      ],
      unavailableReason: null,
    };
  }

  return {
    ...base,
    unavailableReason: pe != null && pe <= 0
      ? "P/E no válido (la empresa reporta pérdidas) y sin rendimiento FCF: valoración por múltiplos no aplicable con los datos actuales."
      : "Fundamentales insuficientes (sin P/E TTM ni rendimiento FCF) para una valoración defendible.",
  };
}
