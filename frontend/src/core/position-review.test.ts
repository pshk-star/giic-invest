import { describe, expect, it } from "vitest";
import { reviewPositions, type PositionReviewInput } from "./position-review";
import type { CompanyValuation } from "./fundamental";

// Tras la auditoría de circularidad: la decisión se apoya en el RENDIMIENTO reportado
// (no circular) vs el retorno exigido (yieldVerdict), no en el upside del múltiplo.
const YIELD: Record<CompanyValuation["yieldVerdict"], number | null> =
  { atractivo: 0.10, razonable: 0.072, caro: 0.03, "n/d": null };

function mkVal(opts: {
  verdict?: CompanyValuation["yieldVerdict"]; quality?: CompanyValuation["quality"];
  cyclical?: boolean; available?: boolean; centralUp?: number;
} = {}): CompanyValuation {
  const { verdict = "razonable", quality = "alta", cyclical = false, available = true, centralUp = 0.05 } = opts;
  const ey = YIELD[verdict];
  const sc = (key: "conservador" | "central" | "favorable", up: number) =>
    ({ key, label: key, fairValue: 100 * (1 + up), upside: up, assumptions: [] });
  return {
    ticker: "X", name: "X", sector: "Tech", price: 100, priceAsOf: "2026-11-01",
    available, method: available ? "pe_eps" : null, horizonLabel: "12 meses",
    epsTtm: 5, peUsed: 20, growthCentral: centralUp,
    scenarios: available ? [sc("conservador", centralUp - 0.1), sc("central", centralUp), sc("favorable", centralUp + 0.2)] : [],
    sensitivity: [], quality,
    dataSources: [], limitations: [], unavailableReason: available ? null : "emisor extranjero 20-F fuera de EDGAR us-gaap",
    epsReported: ey != null ? ey * 100 : null, earningsYield: ey, fcfYield: null, requiredReturn: 0.07,
    yieldVerdict: verdict, cyclical, cyclicalNote: cyclical ? "pico cíclico" : null,
    priceAnchored: true, decisionBasis: "test",
  };
}

function mkItem(p: Partial<PositionReviewInput>): PositionReviewInput {
  return {
    ticker: "X", name: "X", sector: "Tech", kind: "equity", price: 100, priceAsOf: "2026-11-01",
    marketValue: 1000, weight: 0.1, effectiveWeight: 0.1, riskPct: 0.1,
    valuation: mkVal({ verdict: "razonable" }), totalValue: 10000,
    maxWeightAsset: 0.25, maxWeightSector: 0.40, sectorWeight: 0.2, ...p,
  };
}

describe("revisión por posición — disciplina de evidencia (señal no circular)", () => {
  it("concentrada y rendimiento NO atractivo -> REDUCIR (gestión de riesgo, no solo concentración)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.4, marketValue: 4000, valuation: mkVal({ verdict: "razonable" }) })]);
    expect(r.action).toBe("REDUCIR");
    expect(r.targetWeight).toBeCloseTo(0.25, 6);
    expect(r.amountUsd).toBe(-1500); // 0.25*10000 - 4000
    expect(r.rationale.join(" ").toLowerCase()).toContain("no es atractivo");
  });

  it("concentrada pero con rendimiento ATRACTIVO -> MANTENER (no recortar un nombre atractivo por concentración)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.4, marketValue: 4000, valuation: mkVal({ verdict: "atractivo" }) })]);
    expect(r.action).toBe("MANTENER");
  });

  it("cara (rendimiento por debajo del exigido) + concentrada + alta calidad -> VENDER (evidencia convergente)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.4, marketValue: 4000, riskPct: 0.5, valuation: mkVal({ verdict: "caro" }) })]);
    expect(r.action).toBe("VENDER");
    expect(r.amountUsd).toBe(-4000);
  });

  it("cara pero NO concentrada -> no vende (una sola señal no basta)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.1, marketValue: 1000, riskPct: 0.1, valuation: mkVal({ verdict: "caro" }) })]);
    expect(r.action).not.toBe("VENDER");
  });

  it("rendimiento atractivo + espacio + alta calidad -> AUMENTAR modesto", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.1, marketValue: 1000, valuation: mkVal({ verdict: "atractivo" }) })]);
    expect(r.action).toBe("AUMENTAR");
    expect(r.targetWeight).toBeCloseTo(0.15, 6);
    expect(r.amountUsd).toBe(500); // (0.15-0.10)*10000
  });

  it("rendimiento atractivo pero CÍCLICO -> no AUMENTAR (beneficio potencialmente extraordinario)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.1, marketValue: 1000, valuation: mkVal({ verdict: "atractivo", cyclical: true }) })]);
    expect(r.action).not.toBe("AUMENTAR");
  });

  it("sin valoración (extranjero) -> REVISAR y SIEMPRE presente", () => {
    const [r] = reviewPositions([mkItem({ ticker: "ASML", valuation: mkVal({ available: false }) })]);
    expect(r.action).toBe("REVISAR");
    expect(r.valuationLine.toLowerCase()).toMatch(/extranjero|edgar|no disponible/);
  });

  it("calidad de datos baja -> REVISAR (sin acción fuerte)", () => {
    const [r] = reviewPositions([mkItem({ weight: 0.4, marketValue: 4000, valuation: mkVal({ verdict: "caro", quality: "baja" }) })]);
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
      mkItem({ ticker: "A", weight: 0.1, valuation: mkVal({ verdict: "razonable" }) }),
      mkItem({ ticker: "B", weight: 0.4, marketValue: 4000, riskPct: 0.5, valuation: mkVal({ verdict: "caro" }) }),
    ]);
    expect(rs[0].ticker).toBe("B");         // VENDER domina
    expect(rs.map((r) => r.priority)).toEqual([1, 2]);
  });
});
