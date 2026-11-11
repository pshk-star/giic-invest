import { describe, it, expect } from "vitest";
import { buildScanner, type ScanInput } from "./opportunity-scanner";
import { buildAllocationPlan } from "./allocation-planner";
import { buildDecisionRecord } from "./decision-record";
import { evaluateDecision, type PriceMap } from "./decision-eval";

// Barras diarias deterministas desde 2026-01-01.
function daily(base: number, driftPerDay: number, amp: number, phase: number, nDays: number) {
  const out: { as_of: string; close: number }[] = [];
  const start = Date.UTC(2026, 0, 1);
  for (let i = 0; i < nDays; i++) {
    const d = new Date(start + i * 86400000).toISOString().slice(0, 10);
    out.push({ as_of: d, close: base * (1 + driftPerDay * i) * (1 + amp * Math.sin(phase + i * 0.3)) });
  }
  return out;
}
const upTo = (bars: { as_of: string; close: number }[], date: string) => bars.filter((b) => b.as_of <= date);

const EMIT = "2026-01-20T12:00:00.000Z";
const EMIT_D = "2026-01-20";

// Series: AAA sube, BBB sube más, SPY benchmark moderado, CTXT (descartado) baja.
const FULL: PriceMap = {
  AAA: daily(80, 0.0015, 0.05, 1, 220),
  BBB: daily(120, 0.0022, 0.06, 2, 220),
  SPY: daily(400, 0.0008, 0.03, 3, 220),
  NVDA: daily(100, 0.0005, 0.08, 4, 220),
  CTXT: daily(70, -0.0010, 0.07, 5, 220),
};

function emissionInput(): ScanInput {
  const emp = (ticker: string, sector: string, inPortfolio = false) =>
    ({ ticker, name: ticker, sector, country: "US", currency: "USD", assetClass: "equity", kind: "empresa" as const, inPortfolio });
  const histAtEmit: Record<string, { as_of: string; close: number }[]> = {};
  for (const t of Object.keys(FULL)) histAtEmit[t] = upTo(FULL[t], EMIT_D);   // SOLO datos ≤ emisión
  return {
    candidates: [emp("NVDA", "Tech", true), emp("AAA", "Health"), emp("BBB", "Energy"), emp("CTXT", "Industrials")],
    valuation: {
      NVDA: { productiveMargin: -0.30, productiveConfidence: "media", priceComparable: true },
      AAA: { productiveMargin: 0.20, productiveConfidence: "media", priceComparable: true },
      BBB: { productiveMargin: 0.25, productiveConfidence: "media", priceComparable: true },
      CTXT: { productiveMargin: null, productiveConfidence: null, fcffMargin: 0.40, fcffConfidence: "media", priceComparable: true }, // no accionable (fallback off)
    },
    fundamentals: {},
    portfolio: { positions: [{ ticker: "NVDA", sector: "Tech", country: "US", currency: "USD", assetClass: "equity", marketValue: 4000, weight: 1 }], cash: 0 },
    priceHistory: histAtEmit,
    contributions: [3000],
    constraints: { maxPositionWeight: 0.45, maxSectorWeight: 0.50, minMarginToBuy: 0.10 },
  };
}

function record(flags = {}) {
  const input = emissionInput();
  const report = buildScanner(input);
  const plan = buildAllocationPlan(input, report, 3000);
  return buildDecisionRecord({ input, report, plan, benchmark: "SPY", algoVersion: "P2.6", featureFlags: flags, emittedAt: EMIT });
}

describe("P2.6 registro de decisión", () => {
  it("congela recomendaciones, precios de emisión, valoraciones, riesgo y alternativas", () => {
    const r = record();
    expect(r.simulated).toBe(true);
    expect(r.chosen).toBeTruthy();
    expect(r.recommendations.length).toBeGreaterThanOrEqual(1);
    expect(r.pricesAtEmission["SPY"]).toBeGreaterThan(0);
    expect(r.pricesAtEmission["AAA"]).toBeGreaterThan(0);
    expect(r.valuations.find((v) => v.ticker === "AAA")).toBeTruthy();
    expect(r.riskBefore.vol).toBeGreaterThan(0);
    expect(r.alternatives.length).toBeGreaterThanOrEqual(1);     // completa/parcial/efectivo menos la elegida
    expect(r.universe.total).toBeGreaterThan(0);
  });

  it("decisionId determinista (mismos insumos ⇒ mismo id; evita duplicados por re-render)", () => {
    expect(record().decisionId).toBe(record().decisionId);
    expect(record({ VITE_FF_VALPOLICY: true }).decisionId).not.toBe(record().decisionId);
  });

  it("un candidato no accionable (margen positivo pero FCFF, fallback off) NO aparece en recomendaciones", () => {
    const r = record();
    expect(r.recommendations.map((l) => l.ticker)).not.toContain("CTXT");
  });
});

describe("P2.6 evaluación posterior", () => {
  it("sin look-ahead: horizontes no alcanzados no producen retorno", () => {
    const ev = evaluateDecision(record(), FULL, "2026-02-01");   // solo ~12 días desde emisión
    const h1 = ev.horizons.find((h) => h.months === 1)!;
    const h12 = ev.horizons.find((h) => h.months === 12)!;
    expect(h1.reached).toBe(false);
    expect(h1.allocationReturn).toBeNull();
    expect(h12.reached).toBe(false);
  });

  it("horizonte alcanzado: calcula retorno de asignación, efectivo (0%) y benchmark, y excesos", () => {
    const ev = evaluateDecision(record(), FULL, "2026-08-01");   // 1m,3m,6m alcanzados
    const h3 = ev.horizons.find((h) => h.months === 3)!;
    expect(h3.reached).toBe(true);
    expect(h3.allocationReturn).not.toBeNull();
    expect(h3.cashReturn).toBe(0);
    expect(h3.benchmarkReturn).not.toBeNull();
    expect(h3.excessVsCash).toBeCloseTo((h3.allocationReturn as number), 6);
    expect(typeof h3.excessVsBenchmark).toBe("number");
    expect(h3.perLeg.length).toBe(record().recommendations.length);
  });

  it("precio de emisión CONGELADO: el retorno usa el precio del registro, no uno recalculado", () => {
    const r = record();
    const ev = evaluateDecision(r, FULL, "2026-08-01");
    const h3 = ev.horizons.find((h) => h.months === 3)!;
    const leg = h3.perLeg.find((x) => x.ticker === "AAA")!;
    const p0 = r.pricesAtEmission["AAA"]!;
    const p1 = FULL.AAA.filter((b) => b.as_of <= "2026-04-20").slice(-1)[0].close;
    expect(leg.return).toBeCloseTo(p1 / p0 - 1, 3);
  });

  it("datos faltantes ⇒ no disponible (no se inventa rendimiento)", () => {
    const r = record();
    const prices = { ...FULL }; delete (prices as any).AAA;      // sin precios de AAA
    const ev = evaluateDecision(r, prices, "2026-08-01");
    const h3 = ev.horizons.find((h) => h.months === 3)!;
    const leg = h3.perLeg.find((x) => x.ticker === "AAA");
    if (leg) expect(leg.return).toBeNull();
    expect(h3.missing.join(" ")).toMatch(/AAA/);
  });

  it("reproducible y marcada como simulada (no ejecutada)", () => {
    const r = record();
    const a = evaluateDecision(r, FULL, "2026-08-01");
    const b = evaluateDecision(r, FULL, "2026-08-01");
    expect(a).toEqual(b);
    expect(a.simulated).toBe(true);
  });
});
