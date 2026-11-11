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
export type OppClass = "atractiva" | "poco_atractiva" | "evidencia_insuficiente" | "pendiente_analisis";

export interface PositionRec {
  ticker: string; name?: string | null; sector: string | null; action: PositionAction;
  weight: number; riskContribPct: number; margin: number | null; source: string; confidence: string | null;
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
  researchPriorities: { ticker: string; reason: string }[];
  risks: string[];
  constraintsUsed: { maxPositionWeight: number; maxSectorWeight: number; minMarginToBuy: number; sources: Record<string, string> };
  coverage: ScannerReport["coverage"];
  guardrails: string[];
}

export interface BuildAdvisorArgs { profile: Profile; scanInput: ScanInput; asOf?: string }

function classify(e: ScanEntry): { cls: OppClass; buyable: boolean } {
  if (e.margin == null) return { cls: "evidencia_insuficiente", buyable: false };
  if (e.marginSource !== "productivo") return { cls: "pendiente_analisis", buyable: e.actionable };   // FCFF experimental
  if (e.actionable) return { cls: "atractiva", buyable: true };
  return { cls: "poco_atractiva", buyable: false };
}

export function buildUnifiedAdvisor(args: BuildAdvisorArgs): AdvisorReport {
  const { profile } = args;
  const asOf = args.asOf ?? new Date().toISOString().slice(0, 10);
  const c = deriveConstraints(profile);
  const contribution = investableAmount(profile);
  const pol = { fcffFallback: !!args.scanInput.fcffFallback };
  const currency = profile.baseCurrency ?? "USD";

  // constraints del perfil gobiernan TODOS los motores (sin parámetros manuales)
  const scanInput: ScanInput = { ...args.scanInput, constraints: { maxPositionWeight: c.maxPositionWeight, maxSectorWeight: c.maxSectorWeight, minMarginToBuy: c.minMarginToBuy }, contributions: [contribution || 1] };
  const report = buildScanner(scanInput, asOf);

  const positions = scanInput.portfolio.positions;
  const returns = alignReturns(scanInput.priceHistory, positions.map((p) => p.ticker));
  const adv3Input: Adv3Input = {
    positions, cash: scanInput.portfolio.cash, contribution: contribution || 0, returns,
    valuation: scanInput.valuation, quality: Object.fromEntries(positions.map((p) => [p.ticker, { eligible: true, fresh: true }])),
    constraints: scanInput.constraints, etfLookthrough: scanInput.etfLookthrough, fcffFallback: scanInput.fcffFallback,
  };
  const adv3 = buildAdvisor3(adv3Input, asOf);
  const plan = buildAllocationPlan(scanInput, report, contribution);

  // --- acciones por posición (una sola decisión; ACUMULAR = mantener + comprable con holgura) ---
  const portfolioValue = positions.reduce((s, p) => s + p.marketValue, 0) + scanInput.portfolio.cash;
  const weightOf = (mv: number) => (portfolioValue > 0 ? mv / portfolioValue : 0);
  const positionRecs: PositionRec[] = adv3.positionDecisions.map((d) => {
    const p = positions.find((x) => x.ticker === d.ticker)!;
    const w = weightOf(p.marketValue);
    const g = governingValuation(scanInput.valuation[d.ticker], pol);
    let action = d.action as PositionAction;
    const buyCand = passesValueGate(scanInput.valuation[d.ticker], c.minMarginToBuy, pol) && w < c.maxPositionWeight;
    if (action === "MANTENER" && buyCand) action = "ACUMULAR";
    const why = action === "ACUMULAR"
      ? `Infravalorada con confianza suficiente y hay holgura de peso: acumular. ${d.explain.motivos[0] ?? ""}`
      : (d.explain.motivos[0] ?? "");
    return { ticker: d.ticker, name: p.name, sector: p.sector ?? null, action, weight: Number(w.toFixed(4)),
             riskContribPct: Number((d.riskContribPct ?? 0).toFixed(4)), margin: g.margin, source: g.source, confidence: g.conf,
             why, factores: d.explain.factores ?? [] };
  });

  // --- oportunidades (fuera de cartera), clasificadas ---
  const held = new Set(positions.map((p) => p.ticker));
  const opportunities: OpportunityRec[] = report.entries.filter((e) => !held.has(e.ticker) && e.kind !== "etf")
    .map((e) => {
      const { cls, buyable } = classify(e);
      const why = cls === "atractiva" ? "FV productivo con margen y confianza suficientes."
        : cls === "pendiente_analisis" ? "Valoración experimental (FCFF): atractivo preliminar, pendiente de análisis profundo."
        : cls === "poco_atractiva" ? "Valorada pero sin margen suficiente."
        : "Sin valoración concluyente: evidencia insuficiente.";
      return { ticker: e.ticker, name: e.name, sector: e.sector ?? null, class: cls, buyable,
               margin: e.margin, source: e.marginSource, confidence: e.confidence, why };
    })
    .sort((a, b) => {
      const rank: Record<OppClass, number> = { atractiva: 0, pendiente_analisis: 1, poco_atractiva: 2, evidencia_insuficiente: 3 };
      return rank[a.class] - rank[b.class] || (b.margin ?? -9) - (a.margin ?? -9) || a.ticker.localeCompare(b.ticker);
    });

  // prioridades de investigación: experimentales atractivas (Nivel 3 de la evaluación escalonada, Etapa B)
  const researchPriorities = opportunities.filter((o) => o.class === "pendiente_analisis" && (o.margin ?? 0) >= c.minMarginToBuy)
    .slice(0, 8).map((o) => ({ ticker: o.ticker, reason: `Atractivo preliminar (${o.margin != null ? (o.margin * 100).toFixed(0) + "%" : "n/d"}) con valoración experimental; profundizar valoración/escenarios.` }));

  // --- riesgos ---
  const risks: string[] = [];
  if (report.hasConcentrationProblem) risks.push("Concentración elevada en la cartera (un nombre o sector por encima del límite).");
  risks.push(`Volatilidad anual estimada ${(report.baseVol * 100).toFixed(0)}%, HHI sector ${report.baseHhiSector.toFixed(3)}.`);
  const experimentalBuys = plan.proposals.find((x) => x.id === plan.chosen)?.legs.filter((l) => l.confidence !== "alta") ?? [];
  if (experimentalBuys.length) risks.push(`${experimentalBuys.length} nombre(s) de la asignación se apoyan en valoración experimental (FCFF): asignación acotada a propósito.`);
  if (report.coverage.blockedByProductiveVeto.count) risks.push(`${report.coverage.blockedByProductiveVeto.count} oportunidad(es) atractivas por FCFF aún sin FV productivo: pendientes de análisis profundo, no descartadas.`);

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
    opportunities, researchPriorities, risks,
    constraintsUsed: { maxPositionWeight: c.maxPositionWeight, maxSectorWeight: c.maxSectorWeight, minMarginToBuy: c.minMarginToBuy,
                       sources: { empresa: c.posSource, sector: c.sectorSource, margen: c.minMarginSource } },
    coverage: report.coverage,
    guardrails: [
      "Una sola decisión por instrumento (posición / compra nueva / investigación); Scanner, Advisor y asignación comparten la misma política.",
      "FV productivo primario; FCFF experimental acotado y etiquetado (no se trata como confiable).",
      "Heurística de asignación, no optimización de retornos validada; sin predicción de retornos (no validada).",
      "Constraints derivados del perfil/tolerancia (sin parámetros manuales); procedencia visible.",
      "Recomendaciones SIMULADAS; no se ejecutan operaciones. ESPERAR es válido.",
    ],
  };
}

function money(n: number, ccy: string): string {
  return new Intl.NumberFormat("es-MX", { style: "currency", currency: ccy, maximumFractionDigits: 0 }).format(n);
}
