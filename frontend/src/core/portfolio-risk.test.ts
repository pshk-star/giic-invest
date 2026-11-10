import { describe, it, expect } from "vitest";
import {
  riskContributions, annualizedVol, covMatrix, portfolioVariance, portfolioSeries,
  maxDrawdown, beta, marginalImpact,
} from "./portfolio-risk";

// Fixture canónico generado por el motor Python (app/research/portfolio_risk.py). PARIDAD TS↔Python.
const returns: Record<string, number[]> = {
  A: [0.01, -0.02, 0.03, -0.01, 0.0, 0.02, -0.015, 0.012, -0.008, 0.019],
  B: [0.02, -0.01, 0.0, 0.01, -0.02, 0.015, 0.005, -0.012, 0.01, -0.004],
  C: [-0.01, 0.03, -0.02, 0.02, 0.01, -0.03, 0.02, 0.0, 0.015, -0.01],
};
const weights = { A: 0.5, B: 0.3, C: 0.2 };

describe("portfolio-risk (paridad con Python)", () => {
  it("vol de portafolio y Euler coinciden con Python", () => {
    const rc = riskContributions(weights, returns, 252);
    expect(rc.volPortfolioAnnual).toBeCloseTo(0.0942, 4);
    expect(rc.eulerCheck).toBeCloseTo(0.094238, 5);              // Σ contrib == σ_p
    expect(rc.byPosition.A.contribPct).toBeCloseTo(1.2065, 3);
    expect(rc.byPosition.B.contribPct).toBeCloseTo(0.3727, 3);
    expect(rc.byPosition.C.contribPct).toBeCloseTo(-0.5792, 3);  // activo que reduce riesgo (cobertura)
    const sum = Object.values(rc.byPosition).reduce((s, c) => s + c.contribPct, 0);
    expect(sum).toBeCloseTo(1.0, 3);
  });

  it("vol anualizada por activo coincide con Python", () => {
    expect(annualizedVol(returns.A)).toBeCloseTo(0.267187, 5);
    expect(annualizedVol(returns.B)).toBeCloseTo(0.204282, 5);
    expect(annualizedVol(returns.C)).toBeCloseTo(0.311368, 5);
  });

  it("varianza de portafolio coincide con Python", () => {
    const { M } = covMatrix(returns);
    expect(portfolioVariance([0.5, 0.3, 0.2], M)).toBeCloseTo(3.52418e-5, 10);
  });

  it("drawdown del portafolio coincide con Python", () => {
    const dd = maxDrawdown(portfolioSeries(weights, returns));
    expect(dd.maxDrawdown).toBeCloseTo(-0.007, 4);
  });

  it("impacto marginal (reducir A -0.1) coincide con Python", () => {
    const mi = marginalImpact(weights, returns, "A", -0.1, { A: { sector: "T" }, B: { sector: "T" }, C: { sector: "E" } });
    expect(mi.deltaVol).toBeCloseTo(-0.0132, 4);
  });

  it("beta: activo = 2×benchmark => 2", () => {
    const b = [0.01, -0.02, 0.015, -0.005, 0.02];
    expect(beta(b.map((x) => 2 * x), b)).toBeCloseTo(2.0, 9);
  });
});
