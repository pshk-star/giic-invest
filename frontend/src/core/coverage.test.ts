import { describe, expect, it } from "vitest";
import { computeCoverage, type CovItem } from "./coverage";

const it_ = (ticker: string, mv: number, hasPrice: boolean, statOk: boolean, fundOk: boolean, asOf?: string): CovItem =>
  ({ ticker, marketValue: mv, hasPrice, statOk, fundOk, asOf });

describe("cobertura ponderada por valor de mercado", () => {
  it("pondera por patrimonio, no por número de tickers", () => {
    // 1 posición grande cubierta + 3 chicas sin estadística: por tickers sería 25%,
    // por patrimonio es mucho mayor.
    const r = computeCoverage([
      it_("BIG", 9000, true, true, true),
      it_("a", 400, true, false, false),
      it_("b", 300, true, false, false),
      it_("c", 300, true, false, false),
    ]);
    expect(r.total).toBe(10000);
    expect(r.statPct).toBeCloseTo(0.9, 6);       // 9000/10000, no 1/4
    expect(r.uncoveredPct).toBeCloseTo(0.1, 6);
    expect(r.statSufficient).toBe(true);          // 90% >= 80%
  });

  it("marca PARCIAL cuando la cobertura estadística es baja", () => {
    const r = computeCoverage([
      it_("COV", 4000, true, true, true),
      it_("NOHIST", 6000, true, false, false),
    ]);
    expect(r.statPct).toBeCloseTo(0.4, 6);
    expect(r.statSufficient).toBe(false);         // 40% < 80%
    expect(r.topStatGap[0].ticker).toBe("NOHIST");
    expect(r.topStatGap[0].weight).toBeCloseTo(0.6, 6);
  });

  it("niveles A/B/C distintos: precio ≥ estadística ≥ fundamental típico", () => {
    const r = computeCoverage([
      it_("US", 5000, true, true, true),     // precio, stat, fund
      it_("FOR", 3000, true, true, false),   // precio, stat, sin fund
      it_("NEW", 2000, true, false, false),  // precio, sin stat
    ]);
    expect(r.pricePct).toBeCloseTo(1.0, 6);
    expect(r.statPct).toBeCloseTo(0.8, 6);       // US+FOR
    expect(r.fundPct).toBeCloseTo(0.5, 6);       // US
  });

  it("umbrales configurables", () => {
    const base = [it_("A", 7000, true, true, true), it_("B", 3000, true, false, false)];
    expect(computeCoverage(base).statSufficient).toBe(false);                 // 70% < 80%
    expect(computeCoverage(base, { statThreshold: 0.65 }).statSufficient).toBe(true);
  });

  it("fecha más antigua y sin posiciones", () => {
    const r = computeCoverage([it_("A", 100, true, true, true, "2025-06-30"), it_("B", 100, true, true, true, "2026-01-15")]);
    expect(r.oldestAsOf).toBe("2025-06-30");
    expect(computeCoverage([]).total).toBe(0);
  });
});
