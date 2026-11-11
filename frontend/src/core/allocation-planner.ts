// P2.5 — ASIGNACIÓN MULTIPOSICIÓN (EXPERIMENTAL, bajo feature flag). Motor PURO y testeable.
// Distribuye un aporte configurable entre VARIAS oportunidades del universo accionable del Scanner,
// ETF y efectivo, evaluando la cartera RESULTANTE. Responde: "con $X hoy, ¿cuál es la mejor
// distribución razonable dadas valoración, incertidumbre y riesgo?".
//
// Principios (invariantes):
//  - NO optimiza rentabilidad esperada (no hay estimaciones predictivas validadas): el "priority" es
//    un proxy de ATRACTIVO (margen × peso de confianza), nunca un retorno esperado.
//  - Un margen positivo NO es compra automática: el candidato debe ser accionable (pasó la política).
//  - Una valoración experimental de baja confianza NO genera asignación significativa (tope por share).
//  - Límites de concentración por empresa, sector y exposición económica duplicada (ETF look-through).
//  - Conservación EXACTA de capital: Σ importes + efectivo = aporte.
//  - Compara inversión completa, parcial y mantener efectivo; a veces la respuesta es ESPERAR, a veces
//    desplegar — nunca "siempre todo" ni "siempre efectivo".
import type { ScanInput, ScannerReport, ScanEntry } from "./opportunity-scanner";
import { alignReturns } from "./opportunity-scanner";
import { riskContributions, concentration } from "./portfolio-risk";
import type { Conf } from "./valuation-policy";

const CONF_W: Record<string, number> = { alta: 1.0, media: 0.7, baja: 0.3 };
const LOWCONF_MAX_SHARE = 0.15;   // baja confianza: ≤15% del aporte (no asignación significativa)
const DUP_MAX = 0.10;             // exposición ya presente vía ETF por encima de esto ⇒ se descarta/limita
const STRONG_MULT = 2.0;          // "parcial" exige margen ≥ 2× el mínimo
const RISK_PENALTY = 1.5;         // penaliza Δvol en el score de selección de propuesta
const CONC_PENALTY = 1.0;         // penaliza aumento de HHI sector

export interface AllocLeg {
  ticker: string; sector: string | null; amount: number; weightAfter: number;
  basis: "valor" | "diversificador"; confidence: Conf; margin: number | null;
  marginalRiskPct: number | null; duplicatedExposure: number; reason: string;
}
export interface AllocProposal {
  id: "completa" | "parcial" | "efectivo"; label: string;
  legs: AllocLeg[]; deployed: number; cashKept: number;
  volAfter: number; deltaVol: number; hhiSectorAfter: number; deltaHhiSector: number;
  dupExposureTotal: number; qualityDeployed: number; score: number;
  preferred: boolean; why: string;
}
export interface DiscardedCandidate { ticker: string; reason: string }
export interface AllocationPlan {
  contribution: number; cash: number; portfolioValue: number;
  baseVol: number; baseHhiSector: number;
  proposals: AllocProposal[]; chosen: AllocProposal["id"];
  discarded: DiscardedCandidate[]; guardrails: string[];
}

interface Ctx {
  positions: ScanInput["portfolio"]["positions"]; portfolioValue: number; cash: number;
  priceHistory: ScanInput["priceHistory"]; etfLookthrough?: ScanInput["etfLookthrough"];
  meta: Record<string, { sector?: string; country?: string; currency?: string }>;
  baseWeights: Record<string, number>; baseVol: number; baseHhi: number;
  sectorWeight: Record<string, number>; constraints: ScanInput["constraints"];
}

function dupExposure(ctx: Ctx, ticker: string): number {
  if (!ctx.etfLookthrough) return 0;
  let dup = 0;
  for (const p of ctx.positions) {
    const lt = ctx.etfLookthrough[p.ticker]; if (!lt) continue;
    dup += (ctx.baseWeights[p.ticker] ?? 0) * (lt[ticker] ?? 0);
  }
  return dup;
}

// Simula la cartera resultante tras añadir un conjunto de legs (capital nuevo). Determinista.
function simulateSet(ctx: Ctx, legs: { ticker: string; sector: string | null; amount: number }[]) {
  const deployed = legs.reduce((s, l) => s + l.amount, 0);
  const totalAfter = ctx.portfolioValue + deployed;
  const nw: Record<string, number> = {};
  const nmeta = { ...ctx.meta };
  for (const p of ctx.positions) nw[p.ticker] = p.marketValue / totalAfter;
  for (const l of legs) {
    const held = ctx.positions.find((p) => p.ticker === l.ticker);
    nw[l.ticker] = ((held?.marketValue ?? 0) + l.amount) / totalAfter;
    if (!held) nmeta[l.ticker] = { sector: l.sector ?? "na" };
  }
  const simReturns = alignReturns(ctx.priceHistory, Object.keys(nw));
  const rc = riskContributions(nw, simReturns);
  const conc = concentration(nw, nmeta, "sector");
  return { nw, totalAfter, vol: rc.volPortfolioAnnual, hhi: conc.hhi, rc };
}

function priority(e: ScanEntry): number {
  if (e.actionableBasis === "diversificador") return 0.05;    // sleeve pequeño por diversificación (no por margen)
  return Math.max(0, (e.margin ?? 0) * (CONF_W[e.confidence ?? "baja"] ?? 0.3));
}

// Reparte `budget` PROPORCIONAL al atractivo (margen×confianza; NO retorno esperado) para DIVERSIFICAR,
// aplicando topes por empresa, sector, exposición duplicada y valoración experimental. El sobrante de un
// tope queda en EFECTIVO (no se vuelca en otro nombre). Determinista.
function distribute(ctx: Ctx, cands: ScanEntry[], budget: number, contribution: number): AllocLeg[] {
  const prs = cands.map(priority);
  const totalPr = prs.reduce((s, x) => s + x, 0);
  if (totalPr <= 0) return [];
  const maxPos = ctx.constraints.maxPositionWeight;
  const maxSec = ctx.constraints.maxSectorWeight;
  const totalApprox = ctx.portfolioValue + contribution;     // base estable para los topes
  const sectorAcc: Record<string, number> = { ...ctx.sectorWeight };
  const legs: AllocLeg[] = [];
  cands.map((e, i) => ({ e, pr: prs[i] })).sort((a, b) => b.pr - a.pr || a.e.ticker.localeCompare(b.e.ticker)).forEach(({ e, pr }) => {
    const sector = e.sector ?? "na";
    const held = ctx.positions.find((p) => p.ticker === e.ticker);
    const mv = held?.marketValue ?? 0;
    const target = budget * pr / totalPr;                    // reparto proporcional al atractivo
    let cap = Math.max(0, maxPos * totalApprox - mv);        // tope por empresa (peso resultante ≤ maxPos)
    cap = Math.min(cap, Math.max(0, maxSec * totalApprox - (sectorAcc[sector] ?? 0) * totalApprox));  // tope sector
    const experimental = e.confidence === "baja" || e.confidence == null || e.marginSource !== "productivo";
    if (experimental) cap = Math.min(cap, LOWCONF_MAX_SHARE * contribution);   // experimental ⇒ no significativa
    const amount = Math.min(target, cap);                    // sobrante del tope → efectivo (no se vuelca)
    if (amount < 1) return;
    legs.push({
      ticker: e.ticker, sector: e.sector, amount: Math.round(amount), weightAfter: 0,
      basis: (e.actionableBasis ?? "valor"), confidence: e.confidence, margin: e.margin,
      marginalRiskPct: null, duplicatedExposure: Number(dupExposure(ctx, e.ticker).toFixed(4)),
      reason: `margen ${e.margin != null ? (e.margin * 100).toFixed(0) + "%" : "n/d"}, confianza ${e.confidence ?? "n/d"}${why(e)}`,
    });
    sectorAcc[sector] = (sectorAcc[sector] ?? 0) + amount / totalApprox;
  });
  return legs;
}

function why(e: ScanEntry): string {
  if (e.actionableBasis === "diversificador") return "; ETF que reduce concentración";
  if (e.marginSource !== "productivo") return "; valoración experimental (FCFF) ⇒ asignación limitada";
  if (e.confidence === "baja") return "; confianza baja ⇒ asignación limitada";
  return "";
}

function finalizeProposal(ctx: Ctx, id: AllocProposal["id"], label: string, legsIn: AllocLeg[], contribution: number): AllocProposal {
  const sim = simulateSet(ctx, legsIn.map((l) => ({ ticker: l.ticker, sector: l.sector, amount: l.amount })));
  const legs = legsIn.map((l) => {
    const cp = sim.rc.byPosition[l.ticker]?.contribPct;
    return { ...l, weightAfter: Number((sim.nw[l.ticker] ?? 0).toFixed(4)),
             marginalRiskPct: cp != null ? Number(cp.toFixed(4)) : null };
  });
  const deployed = legs.reduce((s, l) => s + l.amount, 0);
  const cashKept = contribution - deployed;
  const qualityDeployed = legs.reduce((s, l) => s + (l.margin ?? 0) * (CONF_W[l.confidence ?? "baja"] ?? 0.3) * l.amount, 0) / (contribution || 1);
  const deltaVol = sim.vol - ctx.baseVol;
  const deltaHhi = ctx.baseHhi - sim.hhi;                    // >0 = reduce concentración
  const dupTotal = Number(legs.reduce((s, l) => s + l.duplicatedExposure, 0).toFixed(4));
  // Score TRANSPARENTE (no retorno esperado): calidad desplegada − penalización por riesgo y concentración.
  const score = Number((qualityDeployed - RISK_PENALTY * Math.max(0, deltaVol) - CONC_PENALTY * Math.max(0, -deltaHhi)).toFixed(4));
  return { id, label, legs, deployed, cashKept, volAfter: Number(sim.vol.toFixed(4)), deltaVol: Number(deltaVol.toFixed(4)),
           hhiSectorAfter: Number(sim.hhi.toFixed(4)), deltaHhiSector: Number(deltaHhi.toFixed(5)),
           dupExposureTotal: dupTotal, qualityDeployed: Number(qualityDeployed.toFixed(4)), score, preferred: false, why: "" };
}

export function buildAllocationPlan(inp: ScanInput, report: ScannerReport, contribution: number): AllocationPlan {
  const positions = inp.portfolio.positions;
  const cash = inp.portfolio.cash;
  const portfolioValue = report.portfolioValue;
  const meta: Record<string, { sector?: string; country?: string; currency?: string }> = {};
  const baseWeights: Record<string, number> = {};
  const sectorWeight: Record<string, number> = {};
  for (const p of positions) {
    meta[p.ticker] = { sector: p.sector ?? "na", country: p.country ?? "na", currency: p.currency ?? "USD" };
    const w = portfolioValue > 0 ? p.marketValue / portfolioValue : 0;
    baseWeights[p.ticker] = w;
    sectorWeight[p.sector ?? "na"] = (sectorWeight[p.sector ?? "na"] ?? 0) + w;
  }
  const ctx: Ctx = { positions, portfolioValue, cash, priceHistory: inp.priceHistory, etfLookthrough: inp.etfLookthrough,
                     meta, baseWeights, baseVol: report.baseVol, baseHhi: report.baseHhiSector, sectorWeight, constraints: inp.constraints };
  const minMargin = inp.constraints.minMarginToBuy ?? 0.10;

  // Universo accionable del Scanner (no solo posiciones): empresas por VALOR + ETF diversificadores.
  const discarded: DiscardedCandidate[] = [];
  const actionable = report.entries.filter((e) => e.actionable);
  const candidates = actionable
    .filter((e) => {
      const dup = dupExposure(ctx, e.ticker);
      if (dup > DUP_MAX) { discarded.push({ ticker: e.ticker, reason: `exposición ya presente vía ETF (${(dup * 100).toFixed(0)}%) > ${DUP_MAX * 100}%` }); return false; }
      return true;
    })
    .sort((a, b) => {
      const pa = (a.margin ?? 0) * (CONF_W[a.confidence ?? "baja"] ?? 0.3);
      const pb = (b.margin ?? 0) * (CONF_W[b.confidence ?? "baja"] ?? 0.3);
      return pb !== pa ? pb - pa : a.ticker.localeCompare(b.ticker);   // determinista
    });
  for (const e of report.entries) {
    if (!e.actionable && e.classification === "atractivo_no_accionable")
      discarded.push({ ticker: e.ticker, reason: "atractivo pero no accionable (confianza/política); no entra a la asignación" });
  }

  // Propuestas
  const completa = finalizeProposal(ctx, "completa", "Inversión completa (dentro de límites)", distribute(ctx, candidates, contribution, contribution), contribution);
  const strong = candidates.filter((e) => (e.margin ?? 0) >= STRONG_MULT * minMargin && (e.confidence === "alta" || e.confidence === "media"));
  const parcial = finalizeProposal(ctx, "parcial", "Inversión parcial (solo alta convicción, resto efectivo)", distribute(ctx, strong, contribution * 0.5, contribution), contribution);
  const efectivo = finalizeProposal(ctx, "efectivo", "Mantener efectivo (ESPERAR)", [], contribution);
  const proposals = [completa, parcial, efectivo];

  // Elección TRANSPARENTE: mejor score, con ESPERAR como suelo. No fuerza desplegar ni fuerza efectivo.
  let chosen: AllocProposal["id"] = "efectivo";
  const deployables = proposals.filter((p) => p.id !== "efectivo" && p.legs.length);
  if (deployables.length) {
    const top = deployables.sort((a, b) => b.score - a.score)[0];
    if (top.score > 0) chosen = top.id;    // aporta calidad neta de riesgo/concentración
  }
  proposals.forEach((p) => { p.preferred = p.id === chosen; });
  const ch = proposals.find((p) => p.id === chosen)!;
  ch.why = chosen === "efectivo"
    ? (candidates.length ? "Ningún despliegue supera el umbral de calidad neta de riesgo/concentración: ESPERAR." : "Sin oportunidades accionables: ESPERAR (válido).")
    : `Mejor calidad desplegada neta de riesgo/concentración (score ${ch.score}); respeta topes de empresa/sector, limita baja confianza y exposición duplicada. Alternativas: ${proposals.filter((p) => p.id !== chosen).map((p) => `${p.id} (score ${p.score})`).join(", ")}.`;

  return {
    contribution, cash, portfolioValue, baseVol: ctx.baseVol, baseHhiSector: ctx.baseHhi,
    proposals, chosen, discarded,
    guardrails: [
      "No optimiza rentabilidad esperada (sin estimaciones predictivas validadas); el priority es atractivo (margen×confianza), no retorno.",
      "Un margen positivo no es compra automática: solo entra el universo accionable (pasó la política de valoración).",
      "La baja confianza se limita al 15% del aporte; la exposición duplicada vía ETF se descarta por encima del 10%.",
      "Límites por empresa y sector respetados; conservación exacta de capital (Σ importes + efectivo = aporte).",
      "Compara completa/parcial/efectivo; ESPERAR es una opción válida. Experimental y reversible; no ejecuta operaciones.",
    ],
  };
}
