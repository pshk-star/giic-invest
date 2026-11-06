import { describe, expect, it } from "vitest";
import { reviewPositions, type PositionReviewInput } from "./position-review";
import type { CompanyValuation } from "./fundamental";

function mkVal(centralUp: number, consUp: number, favUp: number,
               quality: CompanyValuation["quality"], available = true): CompanyValuation {
  const sc = (key: "conservador" | "central" | "favorable", up: number) =>
    ({ key, label: key, fairValue: 100 * (1 + up), upside: up, assumptions: [] });
  return {
    ticker: "X", name: "X", sector: "Tech", price: 100, priceAsOf: "2026-11-01",
    available, method: available ? "pe_eps" : null, horizonLabel: "12 meses",
    epsTtm: 5, peUsed: 20, growthCentral: 0.1,
    scenarios: available ? [sc("conservador", consUp), sc("central", centralUp), sc("favorable", favUp)] : [],
    sensitivity: [], quality,
    dataSources: [], limitations: [], unavailableReason: available ? null : "emisor extranjero 20-F fuera de EDGAR us-gaap",
  };
}

function mkItem(p: Partial<PositionReviewInput>): PositionReviewInput {
  return {
    ticker: "X", name: "X", sector: "Tech", kind: "equity", price: 100, priceAsOf: "2026-11-01",
    marketValue: 1000, weight: 0.1, effectiveWeight: 0.1, riskPct: 0.1,
    valuation: mkVal(0, 0, 0.1, "alta"), totalValue: 10000,
    maxWeightAsset: 0.25, maxWeightSector: 0.40, sectorWeight: 0.2, ...p,
  };
}

describe("revisión por posición — disciplina de evidencia", () => {
  it("concentrada y NO barata -> REDUCIR (gestión de riesgo, no solo concentración)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.4, marketValue: 4000, valuation: mkVal(0.02, -0.1, 0.12, "alta") })]);
    expect(r.action).toBe("REDUCIR");
    expect(r.targetWeight).toBeCloseTo(0.25, 6);
    expect(r.amountUsd).toBe(-1500); // 0.25*10000 - 4000
    expect(r.rationale.join(" ").toLowerCase()).toContain("no es barata");
  });

  it("concentrada pero BARATA -> MANTENER (no recortar un nombre barato por concentración)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.4, marketValue: 4000, valuation: mkVal(0.25, 0.05, 0.4, "alta") })]);
    expect(r.action).toBe("MANTENER");
  });

  it("cara + concentrada + alta calidad -> VENDER (evidencia convergente)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.4, marketValue: 4000, riskPct: 0.5, valuation: mkVal(-0.2, -0.3, 0.0, "alta") })]);
    expect(r.action).toBe("VENDER");
    expect(r.amountUsd).toBe(-4000);
  });

  it("cara pero NO concentrada -> no vende (una sola señal no basta)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.1, marketValue: 1000, riskPct: 0.1, valuation: mkVal(-0.2, -0.3, 0.0, "alta") })]);
    expect(r.action).not.toBe("VENDER");
  });

  it("barata + con espacio + alta calidad -> AUMENTAR modesto", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.1, marketValue: 1000, valuation: mkVal(0.25, 0.05, 0.4, "alta") })]);
    expect(r.action).toBe("AUMENTAR");
    expect(r.targetWeight).toBeCloseTo(0.15, 6);
    expect(r.amountUsd).toBe(500); // (0.15-0.10)*10000
  });

  it("sin valoración (extranjero) -> REVISAR y SIEMPRE presente", () => {
    const [r] = reviewPositions([mkItem({ ticker: "ASML", valuation: mkVal(0, 0, 0, "alta", false) })]);
    expect(r.action).toBe("REVISAR");
    expect(r.valuationLine.toLowerCase()).toMatch(/extranjero|edgar|no disponible/);
  });

  it("calidad de datos baja -> REVISAR (sin acción fuerte)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.4, marketValue: 4000, valuation: mkVal(-0.2, -0.3, 0.0, "baja") })]);
    expect(r.action).toBe("REVISAR");
  });

  it("ETF -> MANTENER por defecto, REVISAR si está sobreponderado (no venta automática)", () => {
    const [keep] = reviewPositions([mkItem({ ticker: "VOO", kind: "etf", weight: 0.2, valuation: null })]);
    expect(keep.action).toBe("MANTENER");
    const [rev] = reviewPositions([mkItem({ ticker: "VOO", kind: "etf", weight: 0.5, valuation: null })]);
    expect(rev.action).toBe("REVISAR");
    expect(["AUMENTAR", "REDUCIR", "VENDER"]).not.toContain(rev.action);
  });

  it("prioriza por severidad y numera (1..n)", () => {
    const rs = reviewPositions([
      mkItem({ ticker: "A", weight: 0.1, valuation: mkVal(0, 0, 0.1, "alta") }),
      mkItem({ ticker: "B", weight: 0.4, marketValue: 4000, riskPct: 0.5, valuation: mkVal(-0.2, -0.3, 0, "alta") }),
    ]);
    expect(rs[0].ticker).toBe("B");         // VENDER domina
    expect(rs.map((r) => r.priority)).toEqual([1, 2]);
  });
});
