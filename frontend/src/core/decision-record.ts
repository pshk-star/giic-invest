// P2.6 — REGISTRO DE DECISIONES (puro). Construye el snapshot INMUTABLE de una recomendación emitida,
// con todo lo necesario para una evaluación posterior SIN look-ahead y SIN recalcular valoraciones.
// No crea modelos nuevos: congela lo que el Scanner + el planner (heurística) produjeron en el momento.
import type { ScanInput, ScannerReport } from "./opportunity-scanner";
import type { AllocationPlan, AllocProposal } from "./allocation-planner";
import { governingValuation } from "./valuation-policy";

export interface DecisionValuation {
  ticker: string; source: string; margin: number | null; confidence: string | null; tier: string;
}
export interface DecisionLeg {
  ticker: string; sector: string | null; amount: number; weightAfter: number;
  basis: string; confidence: string | null; margin: number | null; reason: string; marginalRiskPct: number | null;
}
export interface DecisionRecord {
  decisionId: string;
  emittedAt: string;                 // ISO datetime de emisión
  algoVersion: string;
  featureFlags: Record<string, boolean>;
  benchmark: string;                 // SPY | QQQ
  contribution: number; cash: number; portfolioValue: number;
  universe: { total: number; evaluated: number; excluded: { ticker: string; reason: string }[] };
  pricesAtEmission: Record<string, number | null>;     // precio congelado por ticker involucrado
  valuations: DecisionValuation[];   // valoración usada (fuente/modelo/confianza) por candidato accionable
  portfolio: { ticker: string; sector: string | null; marketValue: number; weight: number }[];
  chosen: AllocProposal["id"];
  recommendations: DecisionLeg[];    // legs de la propuesta elegida (vacío si efectivo)
  riskBefore: { vol: number; hhiSector: number };
  riskAfter: { vol: number; hhiSector: number; deltaVol: number; deltaHhiSector: number };
  alternatives: { id: string; label: string; deployed: number; cashKept: number; score: number; legs: { ticker: string; amount: number }[] }[];
  discardedCandidates: { ticker: string; reason: string }[];
  simulated: true;                   // SIEMPRE: recomendación simulada, NO operación ejecutada
  note: string;
}

// Hash determinista (djb2) → id estable para una misma emisión (evita duplicados por re-render).
function djb2(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h.toString(16);
}

export interface BuildDecisionArgs {
  input: ScanInput; report: ScannerReport; plan: AllocationPlan;
  benchmark?: string; algoVersion?: string; featureFlags?: Record<string, boolean>;
  emittedAt?: string;
}

export function buildDecisionRecord(args: BuildDecisionArgs): DecisionRecord {
  const { input, report, plan } = args;
  const benchmark = args.benchmark ?? "SPY";
  const algoVersion = args.algoVersion ?? "P2.6";
  const featureFlags = args.featureFlags ?? {};
  const emittedAt = args.emittedAt ?? new Date().toISOString();
  const pol = { fcffFallback: !!input.fcffFallback };

  const chosen = plan.proposals.find((p) => p.id === plan.chosen)!;
  const recommendations: DecisionLeg[] = chosen.legs.map((l) => ({
    ticker: l.ticker, sector: l.sector, amount: l.amount, weightAfter: l.weightAfter,
    basis: l.basis, confidence: l.confidence, margin: l.margin, reason: l.reason, marginalRiskPct: l.marginalRiskPct,
  }));

  // precios congelados: posiciones + nombres recomendados + benchmark
  const involved = new Set<string>([benchmark, ...input.portfolio.positions.map((p) => p.ticker), ...recommendations.map((l) => l.ticker)]);
  const pricesAtEmission: Record<string, number | null> = {};
  for (const t of involved) {
    const bars = input.priceHistory[t];
    pricesAtEmission[t] = bars && bars.length ? bars[bars.length - 1].close : null;
  }

  // valoraciones usadas (fuente/confianza/tier) para los candidatos accionables
  const valuations: DecisionValuation[] = report.entries
    .filter((e) => e.actionable)
    .map((e) => {
      const g = governingValuation(input.valuation[e.ticker], pol);
      return { ticker: e.ticker, source: g.source, margin: g.margin, confidence: g.conf, tier: g.tier };
    });

  const portfolio = input.portfolio.positions.map((p) => ({
    ticker: p.ticker, sector: p.sector ?? null, marketValue: p.marketValue,
    weight: report.portfolioValue > 0 ? Number((p.marketValue / report.portfolioValue).toFixed(4)) : 0,
  }));

  const alternatives = plan.proposals.filter((p) => p.id !== plan.chosen).map((p) => ({
    id: p.id, label: p.label, deployed: p.deployed, cashKept: p.cashKept, score: p.score,
    legs: p.legs.map((l) => ({ ticker: l.ticker, amount: l.amount })),
  }));

  const idSeed = JSON.stringify({ emittedAt, algoVersion, featureFlags, contribution: plan.contribution,
    cash: plan.cash, chosen: plan.chosen, recs: recommendations.map((r) => [r.ticker, r.amount]),
    pv: report.portfolioValue });
  const decisionId = "DEC-" + djb2(idSeed);

  return {
    decisionId, emittedAt, algoVersion, featureFlags, benchmark,
    contribution: plan.contribution, cash: plan.cash, portfolioValue: report.portfolioValue,
    universe: { total: report.coverage.total, evaluated: report.coverage.evaluated, excluded: report.excluded },
    pricesAtEmission, valuations, portfolio,
    chosen: plan.chosen, recommendations,
    riskBefore: { vol: plan.baseVol, hhiSector: plan.baseHhiSector },
    riskAfter: { vol: chosen.volAfter, hhiSector: chosen.hhiSectorAfter, deltaVol: chosen.deltaVol, deltaHhiSector: chosen.deltaHhiSector },
    alternatives, discardedCandidates: plan.discarded,
    simulated: true,
    note: "Recomendación SIMULADA (no ejecutada). Snapshot inmutable; evaluación posterior sin look-ahead " +
          "usando precios con as_of ≤ horizonte y las valoraciones congeladas aquí (no recalculadas).",
  };
}
