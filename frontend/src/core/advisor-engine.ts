// Etapa A — ORQUESTADOR del Investment Advisor unificado. Compone los motores YA construidos (Scanner,
// Advisor 3.0, planner de asignación, política de valoración, riesgo) en UNA sola recomendación
// coherente, trazable y reproducible. No duplica lógica ni crea modelos. Una decisión por instrumento;
// distingue acción sobre posición existente, compra nueva y prioridad de investigación.
import { buildScanner, alignReturns, type ScanInput, type ScannerReport, type ScanEntry } from "./opportunity-scanner";
import { buildAdvisor3, passesValueGate, type Adv3Input } from "./advisor3";
import { buildAllocationPlan, type AllocationPlan } from "./allocation-planner";
import { governingValuation } from "./valuation-policy";
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

// Clasificación con separación EXPLÍCITA: compra recomendada (valoración productiva/confiable + accionable)
// / oportunidad analizada (productiva atractiva pero restringida) / candidata de investigación (FCFF
// experimental: NO comprable por sí sola) / poco atractiva / evidencia insuficiente.
function classify(e: ScanEntry, valExp: ReturnType<typeof governingValuation>, minMargin: number): { cls: OppClass; buyable: boolean } {
  // e viene del reporte EJECUTABLE (fallback apagado): productivo gobierna; el FCFF no es accionable.
  if (e.marginSource === "productivo" && e.margin != null) {
    if (e.actionable) return { cls: "compra_recomendada", buyable: true };
    if (e.margin >= minMargin) return { cls: "oportunidad_analizada", buyable: false };   // atractiva pero restringida
    return { cls: "poco_atractiva", buyable: false };
  }
  // sin valoración productiva: ¿hay señal experimental (FCFF) suficiente para investigar?
  if (valExp.source === "fcff_fallback" && valExp.margin != null && valExp.margin >= minMargin) return { cls: "candidata_investigacion", buyable: false };
  if (valExp.margin != null) return { cls: "poco_atractiva", buyable: false };
  return { cls: "evidencia_insuficiente", buyable: false };
}

// Política específica de ETFs/vehículos (no por FCFF): rol, solapamiento, concentración. Costos y
// liquidez: no disponibles en los datos ⇒ se explicita, no se inventan.
function etfPolicy(weight: number, sectorW: number, maxPos: number, maxSector: number, info?: EtfInfo): { action: PositionAction; why: string } {
  const i = info ?? { role: "otro", overlapPct: 0, equityPct: null };
  const roleTxt = i.role === "commodity" ? "exposición a metal/commodity (cobertura/diversificación)"
    : i.role === "equity_amplio" ? "exposición amplia a renta variable" : i.role === "sector" ? "exposición sectorial" : "vehículo";
  const costNote = " Costos (TER) y liquidez: no disponibles en los datos — considéralos antes de operar.";
  if (weight > maxPos) return { action: "REDUCIR", why: `ETF de ${roleTxt} por encima del tope por activo (${(weight * 100).toFixed(0)}% > ${(maxPos * 100).toFixed(0)}%): reducir.` + costNote };
  if (i.role === "equity_amplio" && i.overlapPct > 0.15) return { action: "REDUCIR", why: `ETF de ${roleTxt} con solapamiento alto con tus posiciones directas (${(i.overlapPct * 100).toFixed(0)}%): exposición duplicada, conviene reducir.` + costNote };
  if (sectorW > maxSector) return { action: "REVISAR", why: `ETF de ${roleTxt} en un sector por encima del límite (${(sectorW * 100).toFixed(0)}%): revisar su rol.` + costNote };
  return { action: "MANTENER", why: `ETF de ${roleTxt} dentro de límites y sin solapamiento excesivo: cumple su función en la cartera.` + costNote };
}

export function buildUnifiedAdvisor(args: BuildAdvisorArgs): AdvisorReport {
  const { profile } = args;
  const asOf = args.asOf ?? new Date().toISOString().slice(0, 10);
  const c = deriveConstraints(profile);
  const contribution = investableAmount(profile);
  const execPol = { fcffFallback: false };   // EJECUTABLE: las compras nunca se apoyan en FCFF experimental
  const expPol = { fcffFallback: true };     // sólo para CLASIFICAR candidatas de investigación
  const currency = profile.baseCurrency ?? "USD";

  // constraints del perfil gobiernan TODOS los motores (sin parámetros manuales). El reporte ejecutable
  // usa SOLO valoraciones productivas/confiables (fallback apagado): nada comprable por FCFF experimental.
  const scanInput: ScanInput = { ...args.scanInput, constraints: { maxPositionWeight: c.maxPositionWeight, maxSectorWeight: c.maxSectorWeight, minMarginToBuy: c.minMarginToBuy }, contributions: [contribution || 1], fcffFallback: false };
  const report = buildScanner(scanInput, asOf);

  const positions = scanInput.portfolio.positions;
  const portfolioValue = positions.reduce((s, p) => s + p.marketValue, 0) + scanInput.portfolio.cash;
  const weightOf = (mv: number) => (portfolioValue > 0 ? mv / portfolioValue : 0);
  const sectorWeights: Record<string, number> = {};
  for (const p of positions) sectorWeights[p.sector ?? "na"] = (sectorWeights[p.sector ?? "na"] ?? 0) + weightOf(p.marketValue);

  const returns = alignReturns(scanInput.priceHistory, positions.map((p) => p.ticker));
  const adv3Input: Adv3Input = {
    positions, cash: scanInput.portfolio.cash, contribution: contribution || 0, returns,
    valuation: scanInput.valuation, quality: Object.fromEntries(positions.map((p) => [p.ticker, { eligible: true, fresh: true }])),
    constraints: scanInput.constraints, etfLookthrough: scanInput.etfLookthrough, fcffFallback: false,
  };
  const adv3 = buildAdvisor3(adv3Input, asOf);
  const plan = buildAllocationPlan(scanInput, report, contribution);   // asignación ejecutable (productiva)

  // --- acciones por posición (una sola decisión; ETF con política propia; recortes cuantificados) ---
  const isEtfCls = (ac?: string | null) => ["etf", "fund", "etn", "mutualfund"].includes((ac ?? "").toLowerCase());
  const positionRecs: PositionRec[] = adv3.positionDecisions.map((d) => {
    const p = positions.find((x) => x.ticker === d.ticker)!;
    const w = weightOf(p.marketValue);
    const g = governingValuation(scanInput.valuation[d.ticker], execPol);
    let action = d.action as PositionAction;
    // Para reducir/vender, el porqué incluye el detalle CUANTIFICADO (motivos completos); si no, el principal.
    let why = (d.action === "REDUCIR" || d.action === "VENDER") ? d.explain.motivos.join(" ") : (d.explain.motivos[0] ?? "");
    let trimPct = d.trimPct; let trimAmount = d.trimAmount;
    if (isEtfCls(p.assetClass)) {
      const pol = etfPolicy(w, sectorWeights[p.sector ?? "na"] ?? w, c.maxPositionWeight, c.maxSectorWeight, args.etfInfo?.[p.ticker]);
      action = pol.action; why = pol.why; trimPct = null; trimAmount = null;
    } else {
      const buyCand = passesValueGate(scanInput.valuation[d.ticker], c.minMarginToBuy, execPol) && w < c.maxPositionWeight;
      if (action === "MANTENER" && buyCand) { action = "ACUMULAR"; why = `Infravalorada (FV productivo) con holgura de peso: acumular. ${d.explain.motivos[0] ?? ""}`; }
    }
    return { ticker: d.ticker, name: p.name, sector: p.sector ?? null, action, weight: Number(w.toFixed(4)),
             riskContribPct: Number((d.riskContribPct ?? 0).toFixed(4)), margin: g.margin, source: g.source, confidence: g.conf,
             trimPct, trimAmount, why, factores: d.explain.factores ?? [] };
  });

  // --- oportunidades (fuera de cartera), con separación investigación / analizada / compra ---
  const held = new Set(positions.map((p) => p.ticker));
  const opportunities: OpportunityRec[] = report.entries.filter((e) => !held.has(e.ticker) && e.kind !== "etf")
    .map((e) => {
      const valExp = governingValuation(scanInput.valuation[e.ticker], expPol);
      const { cls, buyable } = classify(e, valExp, c.minMarginToBuy);
      const why = cls === "compra_recomendada" ? "FV productivo con margen y confianza suficientes: compra recomendada."
        : cls === "oportunidad_analizada" ? "FV productivo atractivo, pero no se compra para TU cartera (concentración/límites)."
        : cls === "candidata_investigacion" ? "Señal preliminar por FCFF experimental: candidata de INVESTIGACIÓN, no comprable hasta análisis profundo."
        : cls === "poco_atractiva" ? "Valorada pero sin margen suficiente."
        : "Sin valoración concluyente: evidencia insuficiente.";
      const displayMargin = e.margin ?? valExp.margin;
      return { ticker: e.ticker, name: e.name, sector: e.sector ?? null, class: cls, buyable,
               margin: displayMargin, source: cls === "candidata_investigacion" ? valExp.source : e.marginSource, confidence: e.confidence, why };
    })
    .sort((a, b) => {
      const rank: Record<OppClass, number> = { compra_recomendada: 0, oportunidad_analizada: 1, candidata_investigacion: 2, poco_atractiva: 3, evidencia_insuficiente: 4 };
      return rank[a.class] - rank[b.class] || (b.margin ?? -9) - (a.margin ?? -9) || a.ticker.localeCompare(b.ticker);
    });

  const researchCandidates = opportunities.filter((o) => o.class === "candidata_investigacion")
    .sort((a, b) => (b.margin ?? -9) - (a.margin ?? -9)).slice(0, 10)
    .map((o) => ({ ticker: o.ticker, name: o.name, margin: o.margin, reason: `Señal preliminar FCFF (${o.margin != null ? (o.margin * 100).toFixed(0) + "%" : "n/d"}); requiere valoración productiva/análisis profundo antes de ser comprable.` }));
  const researchPriorities = researchCandidates.slice(0, 8).map((o) => ({ ticker: o.ticker, reason: o.reason }));

  // --- riesgos ---
  const risks: string[] = [];
  if (report.hasConcentrationProblem) risks.push("Concentración elevada en la cartera (un nombre o sector por encima del límite).");
  risks.push(`Volatilidad anual estimada ${(report.baseVol * 100).toFixed(0)}%, HHI sector ${report.baseHhiSector.toFixed(3)}.`);
  if (researchCandidates.length) risks.push(`${researchCandidates.length} candidata(s) de investigación (FCFF experimental) FUERA de la asignación ejecutable: no se compran hasta tener valoración productiva/análisis profundo.`);
  const needData = positionRecs.filter((p) => p.action === "VENDER" || p.action === "REDUCIR");
  if (needData.length) risks.push("Las ventas/reducciones no incorporan horizonte, costos/impuestos ni alternativas de reinversión (datos no disponibles): considéralos antes de ejecutar.");

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
      "Una sola decisión por instrumento; la COMPRA recomendada exige valoración productiva/confiable; la señal FCFF experimental queda en INVESTIGACIÓN, no comprable.",
      "Ninguna compra se basa en una valoración incompleta; las reducciones/ventas se cuantifican y explicitan su incertidumbre.",
      "Heurística de asignación, no optimización de retornos validada; sin predicción de retornos (no validada).",
      "Constraints derivados del perfil/tolerancia (sin parámetros manuales); procedencia visible.",
      "Recomendaciones SIMULADAS; no se ejecutan operaciones. ESPERAR es válido.",
    ],
  };
}

function money(n: number, ccy: string): string {
  return new Intl.NumberFormat("es-MX", { style: "currency", currency: ccy, maximumFractionDigits: 0 }).format(n);
}
