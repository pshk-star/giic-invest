// Etapa A — ORQUESTADOR del Investment Advisor unificado. Compone los motores YA construidos (Scanner,
// Advisor 3.0, planner de asignación, política de valoración, riesgo) en UNA sola recomendación
// coherente, trazable y reproducible. No duplica lógica ni crea modelos. Una decisión por instrumento;
// distingue acción sobre posición existente, compra nueva y prioridad de investigación.
import { buildScanner, alignReturns, type ScanInput, type ScannerReport, type ScanEntry } from "./opportunity-scanner";
import { buildAdvisor3, passesValueGate, type Adv3Input } from "./advisor3";
import { buildAllocationPlan, type AllocationPlan } from "./allocation-planner";
import { governingValuation, type GovInput, type GovResult } from "./valuation-policy";
import { deriveConstraints, investableAmount, type Profile } from "./advisor-profile";

export type PositionAction = "MANTENER" | "ACUMULAR" | "REDUCIR" | "VENDER" | "REVISAR";
// Separa explícitamente candidata de investigación / oportunidad analizada / compra recomendada.
export type OppClass = "compra_recomendada" | "oportunidad_analizada" | "candidata_investigacion" | "poco_atractiva" | "evidencia_insuficiente";

export interface EtfInfo { role: "equity_amplio" | "sector" | "commodity" | "otro"; overlapPct: number; equityPct: number | null }

export interface PositionRec {
  ticker: string; name?: string | null; sector: string | null; action: PositionAction;
  weight: number; riskContribPct: number; margin: number | null; source: string; confidence: string | null;
  trimPct: number | null; trimAmount: number | null;
  why: string; factores: string[];
}
export interface OpportunityRec {
  ticker: string; name?: string | null; sector: string | null; class: OppClass;
  buyable: boolean; margin: number | null; source: string; confidence: string | null; why: string;
  review?: boolean;   // BARRERA: valoración en revisión (inconsistencia económica) ⇒ nunca comprable
}
export interface AdvisorReport {
  asOf: string; currency: string;
  posture: "desplegar" | "parcial" | "esperar";
  executiveSummary: string;
  positions: PositionRec[];
  newMoney: {
    contribution: number; chosen: AllocationPlan["chosen"];
    legs: { ticker: string; amount: number; weightAfter: number; reason: string }[];
    cashKept: number; volBefore: number; volAfter: number; why: string;
    alternatives: { id: string; deployed: number; cashKept: number; score: number }[];
  };
  opportunities: OpportunityRec[];
  researchCandidates: { ticker: string; name?: string | null; margin: number | null; reason: string }[];
  researchPriorities: { ticker: string; reason: string }[];
  risks: string[];
  constraintsUsed: { maxPositionWeight: number; maxSectorWeight: number; minMarginToBuy: number; sources: Record<string, string> };
  coverage: ScannerReport["coverage"];
  guardrails: string[];
}

export interface BuildAdvisorArgs { profile: Profile; scanInput: ScanInput; etfInfo?: Record<string, EtfInfo>; asOf?: string }

// Clasificación bajo la POLÍTICA ÚNICA (P2.4): el flag de fallback YA está aplicado en `g` (la valoración
// gobernante). Separación EXPLÍCITA:
//  - compra_recomendada: FV PRODUCTIVO (confiable) con margen+confianza y accionable para la cartera.
//  - oportunidad_analizada: (a) FCFF como FALLBACK bajo controles (confianza suficiente, no extremo) y
//    accionable ⇒ comprable a TIER EXPERIMENTAL (menor convicción, nunca al nivel de un FV productivo);
//    o (b) valorada y atractiva pero RESTRINGIDA por límites de cartera ⇒ no comprable.
//  - candidata_investigacion: hay señal FCFF que NO gobierna la decisión (confianza insuficiente o el flag
//    VALPOLICY apagado) ⇒ sólo investigación, no comprable.
//  - poco_atractiva / evidencia_insuficiente.
// Un margen positivo por sí solo nunca basta: `passesValueGate`/`governingValuation` exigen confianza y
// fuente gobernante. No se modifican Fair Values para producir compras.
function classify(e: ScanEntry, v: GovInput | undefined, g: GovResult, minMargin: number): { cls: OppClass; buyable: boolean } {
  if (g.source === "productivo" && g.margin != null) {
    if (e.actionable) return { cls: "compra_recomendada", buyable: true };
    if (g.margin >= minMargin) return { cls: "oportunidad_analizada", buyable: false };   // productiva atractiva pero restringida
    return { cls: "poco_atractiva", buyable: false };
  }
  if (g.source === "fcff_fallback" && g.margin != null) {                                   // FCFF accionable bajo VALPOLICY (controles superados)
    if (g.margin >= minMargin && e.actionable) return { cls: "oportunidad_analizada", buyable: true };   // comprable, tier experimental
    if (g.margin >= minMargin) return { cls: "oportunidad_analizada", buyable: false };     // superó margen/confianza pero restringida
    return { cls: "poco_atractiva", buyable: false };
  }
  // FCFF sólo como CONTEXTO (fallback apagado) o confianza insuficiente: no gobierna ⇒ INVESTIGACIÓN.
  const ctx = g.margin ?? v?.fcffMargin ?? null;
  if (ctx != null && ctx >= minMargin) return { cls: "candidata_investigacion", buyable: false };
  if (ctx != null) return { cls: "poco_atractiva", buyable: false };
  return { cls: "evidencia_insuficiente", buyable: false };
}

// Política específica de ETFs/vehículos (no por FCFF): rol, solapamiento, concentración. Costos y
// liquidez: no disponibles en los datos ⇒ se explicita, no se inventan.
// Evalúa cada ETF por su NATURALEZA (rol, solapamiento, peso), no por carecer de FCFF ni por agrupar
// todos los vehículos en un pseudo-sector. La concentración agregada de vehículos se reporta aparte.
function etfPolicy(weight: number, maxPos: number, info?: EtfInfo): { action: PositionAction; why: string } {
  const i = info ?? { role: "otro", overlapPct: 0, equityPct: null };
  const roleTxt = i.role === "commodity" ? "exposición a metal/commodity (cobertura/diversificación)"
    : i.role === "equity_amplio" ? "exposición amplia a renta variable" : i.role === "sector" ? "exposición sectorial" : "vehículo";
  const costNote = " Costos (TER) y liquidez: no disponibles en los datos — considéralos antes de operar.";
  if (weight > maxPos) return { action: "REDUCIR", why: `ETF de ${roleTxt} por encima del tope por activo (${(weight * 100).toFixed(0)}% > ${(maxPos * 100).toFixed(0)}%): reducir.` + costNote };
  if (i.role === "equity_amplio" && i.overlapPct > 0.15) return { action: "REDUCIR", why: `ETF de ${roleTxt} con solapamiento alto con tus posiciones directas (${(i.overlapPct * 100).toFixed(0)}%): exposición duplicada, conviene reducir.` + costNote };
  return { action: "MANTENER", why: `ETF de ${roleTxt} dentro del tope por activo y sin solapamiento excesivo (${(i.overlapPct * 100).toFixed(0)}%): cumple su función en la cartera.` + costNote };
}

export function buildUnifiedAdvisor(args: BuildAdvisorArgs): AdvisorReport {
  const { profile } = args;
  const asOf = args.asOf ?? new Date().toISOString().slice(0, 10);
  const c = deriveConstraints(profile);
  const contribution = investableAmount(profile);
  // POLÍTICA ÚNICA (P2.4): un solo valor de fallback gobierna Scanner, Advisor 3.0, asignación y
  // clasificación. Proviene del flag VITE_FF_VALPOLICY (cableado en scanInput.fcffFallback por la página).
  // El orquestador NO lo sobrescribe: honra la política compartida en lugar de reimponer "sólo productivo".
  const fallback = !!args.scanInput.fcffFallback;
  const pol = { fcffFallback: fallback };
  const currency = profile.baseCurrency ?? "USD";

  // constraints del perfil gobiernan TODOS los motores (sin parámetros manuales); el flag de fallback se
  // propaga sin cambios para que ninguna etapa reintroduzca restricciones que P2.4 ya resolvió.
  const scanInput: ScanInput = { ...args.scanInput, constraints: { maxPositionWeight: c.maxPositionWeight, maxSectorWeight: c.maxSectorWeight, minMarginToBuy: c.minMarginToBuy }, contributions: [contribution || 1], fcffFallback: fallback };
  const report = buildScanner(scanInput, asOf);

  const positions = scanInput.portfolio.positions;
  const portfolioValue = positions.reduce((s, p) => s + p.marketValue, 0) + scanInput.portfolio.cash;
  const weightOf = (mv: number) => (portfolioValue > 0 ? mv / portfolioValue : 0);
  const isEtfAC = (ac?: string | null) => ["etf", "fund", "etn", "mutualfund"].includes((ac ?? "").toLowerCase());
  const vehicleWeight = positions.filter((p) => isEtfAC(p.assetClass)).reduce((s, p) => s + weightOf(p.marketValue), 0);

  const returns = alignReturns(scanInput.priceHistory, positions.map((p) => p.ticker));
  const adv3Input: Adv3Input = {
    positions, cash: scanInput.portfolio.cash, contribution: contribution || 0, returns,
    valuation: scanInput.valuation, quality: Object.fromEntries(positions.map((p) => [p.ticker, { eligible: true, fresh: true }])),
    constraints: scanInput.constraints, etfLookthrough: scanInput.etfLookthrough, fcffFallback: fallback,
  };
  const adv3 = buildAdvisor3(adv3Input, asOf);
  const plan = buildAllocationPlan(scanInput, report, contribution);   // asignación ejecutable (productiva)

  // --- acciones por posición (una sola decisión; ETF con política propia; recortes cuantificados) ---
  const positionRecs: PositionRec[] = adv3.positionDecisions.map((d) => {
    const p = positions.find((x) => x.ticker === d.ticker)!;
    const w = weightOf(p.marketValue);
    const g = governingValuation(scanInput.valuation[d.ticker], pol);
    let action = d.action as PositionAction;
    // Para reducir/vender, el porqué incluye el detalle CUANTIFICADO (motivos completos); si no, el principal.
    let why = (d.action === "REDUCIR" || d.action === "VENDER") ? d.explain.motivos.join(" ") : (d.explain.motivos[0] ?? "");
    let trimPct = d.trimPct; let trimAmount = d.trimAmount;
    if (isEtfAC(p.assetClass)) {
      const pol = etfPolicy(w, c.maxPositionWeight, args.etfInfo?.[p.ticker]);
      action = pol.action; why = pol.why; trimPct = null; trimAmount = null;
    } else {
      const buyCand = passesValueGate(scanInput.valuation[d.ticker], c.minMarginToBuy, pol) && w < c.maxPositionWeight;
      if (action === "MANTENER" && buyCand) { action = "ACUMULAR"; why = `Infravalorada (${g.source === "fcff_fallback" ? "FCFF fallback, confianza " + g.conf : "FV productivo"}) con holgura de peso: acumular. ${d.explain.motivos[0] ?? ""}`; }
    }
    return { ticker: d.ticker, name: p.name, sector: p.sector ?? null, action, weight: Number(w.toFixed(4)),
             riskContribPct: Number((d.riskContribPct ?? 0).toFixed(4)), margin: g.margin, source: g.source, confidence: g.conf,
             trimPct, trimAmount, why, factores: d.explain.factores ?? [] };
  });

  // --- oportunidades (fuera de cartera), con separación investigación / analizada / compra ---
  const held = new Set(positions.map((p) => p.ticker));
  const opportunities: OpportunityRec[] = report.entries.filter((e) => !held.has(e.ticker) && e.kind !== "etf")
    .map((e) => {
      const v = scanInput.valuation[e.ticker];
      const g = governingValuation(v, pol);
      let { cls, buyable } = classify(e, v, g, c.minMarginToBuy);
      // BARRERA: valoración en revisión ⇒ nunca comprable; se muestra como INVESTIGACIÓN (en revisión).
      if (g.blocked) { cls = "candidata_investigacion"; buyable = false; }
      const why = g.blocked ? `EN REVISIÓN — no comprable: ${g.blockReason ?? "inconsistencia económica no resuelta"}. El Fair Value no se usa para asignar capital hasta corregir el motor.`
        : cls === "compra_recomendada" ? "FV productivo con margen y confianza suficientes: compra recomendada."
        : cls === "oportunidad_analizada" && buyable ? `Accionable por FCFF como fallback bajo controles (confianza ${g.conf}, tier experimental): oportunidad analizada, menor convicción que un FV productivo.`
        : cls === "oportunidad_analizada" ? "Valorada y atractiva, pero restringida para TU cartera (concentración/límites de peso)."
        : cls === "candidata_investigacion" ? "Señal por FCFF que NO gobierna la decisión (confianza insuficiente o VALPOLICY apagado): candidata de INVESTIGACIÓN, no comprable hasta análisis profundo."
        : cls === "poco_atractiva" ? "Valorada pero sin margen suficiente."
        : "Sin valoración concluyente: evidencia insuficiente.";
      const displayMargin = g.margin ?? e.margin ?? v?.fcffMargin ?? null;
      return { ticker: e.ticker, name: e.name, sector: e.sector ?? null, class: cls, buyable,
               margin: displayMargin, source: g.source, confidence: g.conf, why, review: !!g.blocked };
    })
    .sort((a, b) => {
      const rank: Record<OppClass, number> = { compra_recomendada: 0, oportunidad_analizada: 1, candidata_investigacion: 2, poco_atractiva: 3, evidencia_insuficiente: 4 };
      return rank[a.class] - rank[b.class] || (b.margin ?? -9) - (a.margin ?? -9) || a.ticker.localeCompare(b.ticker);
    });

  const researchCandidates = opportunities.filter((o) => o.class === "candidata_investigacion")
    .sort((a, b) => (b.margin ?? -9) - (a.margin ?? -9)).slice(0, 10)
    .map((o) => ({ ticker: o.ticker, name: o.name, margin: o.margin, reason: o.review ? o.why : `Señal preliminar FCFF (${o.margin != null ? (o.margin * 100).toFixed(0) + "%" : "n/d"}); requiere valoración productiva/análisis profundo antes de ser comprable.` }));
  const reviewBlocked = opportunities.filter((o) => o.review);
  const researchPriorities = researchCandidates.slice(0, 8).map((o) => ({ ticker: o.ticker, reason: o.reason }));

  // --- riesgos ---
  const risks: string[] = [];
  if (report.hasConcentrationProblem) risks.push("Concentración elevada en la cartera (un nombre o sector por encima del límite).");
  risks.push(`Volatilidad anual estimada ${(report.baseVol * 100).toFixed(0)}%, HHI sector ${report.baseHhiSector.toFixed(3)}.`);
  if (vehicleWeight > c.maxSectorWeight) risks.push(`Los vehículos (ETF) suman ${(vehicleWeight * 100).toFixed(0)}% de la cartera (incluye renta variable amplia y metales): revisa la concentración agregada en vehículos.`);
  if (researchCandidates.length) risks.push(`${researchCandidates.length} candidata(s) de investigación (FCFF experimental) FUERA de la asignación ejecutable: no se compran hasta tener valoración productiva/análisis profundo.`);
  if (reviewBlocked.length) risks.push(`BARRERA DE SEGURIDAD: ${reviewBlocked.length} valoración(es) EN REVISIÓN por inconsistencia económica no resuelta (${reviewBlocked.map((o) => o.ticker).join(", ")}): bloqueadas para compra/asignación hasta corregir el motor. Los Fair Values no se alteran.`);
  const needData = positionRecs.filter((p) => p.action === "VENDER" || p.action === "REDUCIR");
  if (needData.length) risks.push("Las ventas/reducciones son ESCENARIOS INDICATIVOS, no instrucciones ejecutables: el % de recorte deriva del margen productivo (½·|margen|, acotado) y NO incorpora horizonte, costos/impuestos ni alternativas de reinversión; considéralos antes de ejecutar.");

  // --- resumen y postura ---
  const chosen = plan.proposals.find((x) => x.id === plan.chosen)!;
  const posture: AdvisorReport["posture"] = plan.chosen === "completa" ? "desplegar" : plan.chosen === "parcial" ? "parcial" : "esperar";
  const nAcc = positionRecs.filter((p) => p.action === "ACUMULAR").length;
  const nRed = positionRecs.filter((p) => p.action === "REDUCIR" || p.action === "VENDER").length;
  const nRev = positionRecs.filter((p) => p.action === "REVISAR").length;
  const deployN = chosen.legs.length;
  const executiveSummary = posture === "esperar"
    ? `Hoy: mantener la cartera y CONSERVAR el efectivo — ${plan.discarded.length || opportunities.length ? "las oportunidades no superan el umbral de calidad neta de riesgo" : "sin oportunidades accionables"}. ${nRed ? nRed + " posición(es) a reducir. " : ""}${nRev ? nRev + " a revisar." : ""}`
    : `Hoy: ${posture === "desplegar" ? "desplegar" : "desplegar parcialmente"} ${money(chosen.deployed, currency)} en ${deployN} nombre(s) y conservar ${money(chosen.cashKept, currency)}. ${nAcc ? nAcc + " posición(es) para acumular. " : ""}${nRed ? nRed + " a reducir. " : ""}${nRev ? nRev + " a revisar." : ""}`;

  return {
    asOf, currency, posture, executiveSummary,
    positions: positionRecs,
    newMoney: {
      contribution, chosen: plan.chosen,
      legs: chosen.legs.map((l) => ({ ticker: l.ticker, amount: l.amount, weightAfter: l.weightAfter, reason: l.reason })),
      cashKept: chosen.cashKept, volBefore: plan.baseVol, volAfter: chosen.volAfter, why: chosen.why,
      alternatives: plan.proposals.filter((x) => x.id !== plan.chosen).map((x) => ({ id: x.id, deployed: x.deployed, cashKept: x.cashKept, score: x.score })),
    },
    opportunities, researchCandidates, researchPriorities, risks,
    constraintsUsed: { maxPositionWeight: c.maxPositionWeight, maxSectorWeight: c.maxSectorWeight, minMarginToBuy: c.minMarginToBuy,
                       sources: { empresa: c.posSource, sector: c.sectorSource, margen: c.minMarginSource } },
    coverage: report.coverage,
    guardrails: [
      `Política de valoración ÚNICA (P2.4) compartida por Scanner, Advisor 3.0 y asignación: el FV productivo gobierna; el FCFF actúa como FALLBACK accionable sólo con confianza suficiente y margen no extremo cuando VALPOLICY está activo (tier experimental, menor convicción). Fallback VALPOLICY: ${fallback ? "ACTIVO (FCFF gobierna como fallback bajo controles)" : "inactivo (sólo el FV productivo gobierna compras; FCFF = contexto)"}.`,
      "Un margen positivo por sí solo no habilita compra: exige confianza suficiente y fuente gobernante. El FCFF que no supera los controles queda en INVESTIGACIÓN. No se modifican Fair Values para producir compras.",
      "Ninguna compra se basa en una valoración incompleta; las reducciones/ventas se cuantifican y explicitan su incertidumbre.",
      "Montos de asignación = PROPUESTAS EXPERIMENTALES condicionadas por límites y heurísticas, NO asignaciones óptimas ni optimización de retornos validada (sin predicción de retornos).",
      "Constraints derivados del perfil/tolerancia (sin parámetros manuales); procedencia visible.",
      "Recomendaciones SIMULADAS; no se ejecutan operaciones. ESPERAR es válido.",
    ],
  };
}

function money(n: number, ccy: string): string {
  return new Intl.NumberFormat("es-MX", { style: "currency", currency: ccy, maximumFractionDigits: 0 }).format(n);
}
