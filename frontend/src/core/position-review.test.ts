import { describe, expect, it } from "vitest";
import { reviewPositions, type PositionReviewInput } from "./position-review";
import type { CompanyValuation } from "./fundamental";

// Tras degradar la criba: NO hay decisiones por valoración (ni AUMENTAR ni VENDER).
// REDUCIR sólo por concentración/riesgo (reversible). REVISAR ante calidad baja, alerta
// de ciclicidad o inconsistencia EPS. MANTENER por defecto.
function mkVal(o: {
  quality?: CompanyValuation["quality"]; cyclicalAlert?: boolean; epsConsistent?: boolean | null;
  available?: boolean; yieldVsReference?: CompanyValuation["yieldVsReference"]; earningsYield?: number | null;
} = {}): CompanyValuation {
  const { quality = "alta", cyclicalAlert = false, epsConsistent = true, available = true,
          yieldVsReference = "cerca", earningsYield = 0.072 } = o;
  const sc = (key: "conservador" | "central" | "favorable", up: number) =>
    ({ key, label: key, fairValue: 100 * (1 + up), upside: up, assumptions: [] });
  return {
    ticker: "X", name: "X", sector: "Tech", price: 100, priceAsOf: "2026-11-01",
    available, method: available ? "pe_eps" : null, horizonLabel: "12 meses",
    epsTtm: 5, peUsed: 20, growthCentral: 0.05,
    scenarios: available ? [sc("conservador", -0.05), sc("central", 0.05), sc("favorable", 0.25)] : [],
    sensitivity: [], quality,
    dataSources: [], limitations: [], unavailableReason: available ? null : "emisor extranjero 20-F fuera de EDGAR us-gaap",
    epsReported: earningsYield != null ? earningsYield * 100 : null, earningsBasis: "reported_annual",
    ttmEps: null, normalizedEps: null, forwardEps: null,
    earningsYield, fcfYield: null, referenceYield: 0.07, yieldVsReference,
    cyclicalAlert, cyclicalNote: cyclicalAlert ? "alerta" : null, epsConsistent, consistencyNotes: [],
    priceAnchored: true, decisionReady: false, decisionBlock: "sin valoración fundada", decisionBasis: "test",
  };
}

function mkItem(p: Partial<PositionReviewInput>): PositionReviewInput {
  return {
    ticker: "X", name: "X", sector: "Tech", kind: "equity", price: 100, priceAsOf: "2026-11-01",
    marketValue: 1000, weight: 0.1, effectiveWeight: 0.1, riskPct: 0.1,
    valuation: mkVal(), totalValue: 10000,
    maxWeightAsset: 0.25, maxWeightSector: 0.40, sectorWeight: 0.2, ...p,
  };
}

describe("revisión por posición — sin decisiones por valoración", () => {
  it("concentrada → REDUCIR (gestión de riesgo, reversible, independiente de valoración)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.4, marketValue: 4000, valuation: mkVal({ yieldVsReference: "encima", earningsYield: 0.12 }) })]);
    expect(r.action).toBe("REDUCIR");
    expect(r.targetWeight).toBeCloseTo(0.25, 6);
    expect(r.amountUsd).toBe(-1500); // 0.25*10000 - 4000
    expect(r.rationale.join(" ").toLowerCase()).toContain("riesgo");
  });

  it("NUNCA emite VENDER por valoración, aunque esté 'debajo' de la referencia y concentrada", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.4, marketValue: 4000, riskPct: 0.5, valuation: mkVal({ yieldVsReference: "debajo", earningsYield: 0.02 }) })]);
    expect(r.action).toBe("REDUCIR");      // riesgo, no VENDER
    expect(r.action).not.toBe("VENDER");
  });

  it("NUNCA emite AUMENTAR por valoración, aunque el rendimiento esté 'encima' y haya espacio", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.1, marketValue: 1000, valuation: mkVal({ yieldVsReference: "encima", earningsYield: 0.15 }) })]);
    expect(r.action).toBe("MANTENER");
    expect(["AUMENTAR", "VENDER"]).not.toContain(r.action);
  });

  it("alerta de ciclicidad → REVISAR (no afirma pico, no decide)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.1, valuation: mkVal({ cyclicalAlert: true }) })]);
    expect(r.action).toBe("REVISAR");
  });

  it("inconsistencia EPS/acciones/ADR → REVISAR", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.1, valuation: mkVal({ epsConsistent: false }) })]);
    expect(r.action).toBe("REVISAR");
  });

  it("sin valoración (extranjero) → REVISAR y SIEMPRE presente", () => {
    const [r] = reviewPositions([mkItem({ ticker: "ASML", valuation: mkVal({ available: false }) })]);
    expect(r.action).toBe("REVISAR");
    expect(r.valuationLine.toLowerCase()).toMatch(/extranjero|edgar|no disponible/);
  });

  it("calidad de datos baja → REVISAR", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.1, valuation: mkVal({ quality: "baja" }) })]);
    expect(r.action).toBe("REVISAR");
  });

  it("dentro de límites y datos ok → MANTENER (ni compra ni venta por valoración)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.1 })]);
    expect(r.action).toBe("MANTENER");
  });

  it("ETF → MANTENER por defecto, REVISAR si está sobreponderado (no venta automática)", () => {
    const [keep] = reviewPositions([mkItem({ ticker: "VOO", kind: "etf", weight: 0.2, valuation: null })]);
    expect(keep.action).toBe("MANTENER");
    const [rev] = reviewPositions([mkItem({ ticker: "VOO", kind: "etf", weight: 0.5, valuation: null })]);
    expect(rev.action).toBe("REVISAR");
    expect(["AUMENTAR", "REDUCIR", "VENDER"]).not.toContain(rev.action);
  });

  it("prioriza por severidad y numera (1..n)", () => {
    const rs = reviewPositions([
      mkItem({ ticker: "A", weight: 0.1 }),                                   // MANTENER (bajo)
      mkItem({ ticker: "B", weight: 0.4, marketValue: 4000, riskPct: 0.5 }),  // REDUCIR (alto)
    ]);
    expect(rs[0].ticker).toBe("B");
    expect(rs.map((r) => r.priority)).toEqual([1, 2]);
  });
});
