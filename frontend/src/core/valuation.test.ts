import { describe, expect, it } from "vitest";
import {
  type FundamentalsPayload, fairValueByFcfYield, fairValueByPE, impliedFcfGrowth,
  median, missingFundamentals, peerMedian, riskFlags,
} from "./valuation";

const F = (o: Partial<FundamentalsPayload> = {}): FundamentalsPayload => ({
  pe_ttm: null, pe_forward: null, ev_ebitda: null, fcf_yield: null, roic: null,
  roe: null, rev_growth_yoy: null, eps_growth_yoy: null, net_margin: null,
  debt_to_equity: null, market_cap: null, ...o,
});

describe("estadística de pares", () => {
  it("median ignora nulos e infinitos", () => {
    expect(median([10, null, 20, undefined, 30])).toBe(20);
    expect(median([])).toBeNull();
  });
  it("peerMedian por P/E positivo", () => {
    expect(peerMedian([F({ pe_ttm: 10 }), F({ pe_ttm: 20 }), F({ pe_ttm: -5 })], "pe_ttm")).toBe(15);
  });
});

describe("valor relativo", () => {
  it("P/E barato vs mediana implica upside", () => {
    const fv = fairValueByPE(10, 20)!;        // empresa a 10×, sector 20× -> +100%
    expect(fv.upsidePct).toBeCloseTo(1.0, 6);
  });
  it("P/E caro vs mediana implica downside", () => {
    const fv = fairValueByPE(40, 20)!;        // -50%
    expect(fv.upsidePct).toBeCloseTo(-0.5, 6);
  });
  it("devuelve null si falta el dato", () => {
    expect(fairValueByPE(null, 20)).toBeNull();
    expect(fairValueByFcfYield(0.05, null)).toBeNull();
  });
  it("FCF yield mayor que pares implica upside", () => {
    const fv = fairValueByFcfYield(0.08, 0.04)!;   // yield doble -> +100%
    expect(fv.upsidePct).toBeCloseTo(1.0, 6);
  });
});

describe("lectura inversa (crecimiento implícito)", () => {
  it("g ≈ r − fcf_yield", () => {
    expect(impliedFcfGrowth(0.04, 0.09)).toBeCloseTo(0.05, 6);
    expect(impliedFcfGrowth(null, 0.09)).toBeNull();
  });
});

describe("riesgos y faltantes", () => {
  it("marca prima de valoración y contracción de ingresos", () => {
    const flags = riskFlags(F({ pe_ttm: 30, rev_growth_yoy: -0.1 }), 20, null);
    expect(flags.join(" ")).toContain("prima");
    expect(flags.join(" ")).toContain("contracción");
  });
  it("lista los fundamentales no disponibles (ROIC, EV/EBITDA, P/E forward)", () => {
    const miss = missingFundamentals(F({ pe_ttm: 18, roe: 0.3 }));
    expect(miss).toContain("ROIC");
    expect(miss).toContain("EV/EBITDA");
    expect(miss).toContain("P/E forward");
    expect(miss).not.toContain("P/E ttm");
  });
});
