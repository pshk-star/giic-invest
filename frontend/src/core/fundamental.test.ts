import { describe, expect, it } from "vitest";
import { valuateCompany, type FundamentalInput } from "./fundamental";
import type { FundamentalsPayload } from "./valuation";

const payload = (p: Partial<FundamentalsPayload>): FundamentalsPayload => ({
  pe_ttm: null, pe_forward: null, ev_ebitda: null, fcf_yield: null, roic: null,
  roe: null, rev_growth_yoy: null, eps_growth_yoy: null, net_margin: null,
  debt_to_equity: null, market_cap: null, ...p,
});

const input = (p: Partial<FundamentalInput>): FundamentalInput => ({
  ticker: "X", name: "X", sector: "Tech", price: 100, priceAsOf: "2026-11-01",
  f: payload({}), ...p,
});

describe("valoración fundamental — método P/E × EPS", () => {
  it("central = EPS·(1+g)·P/E actual; 3 escenarios ordenados", () => {
    const r = valuateCompany(input({ price: 100, f: payload({ pe_ttm: 20, eps_growth_yoy: 0.10 }) }));
    expect(r.available).toBe(true);
    expect(r.method).toBe("pe_eps");
    expect(r.epsTtm).toBeCloseTo(5, 6);
    const central = r.scenarios.find((s) => s.key === "central")!;
    expect(central.fairValue).toBeCloseTo(110, 6);     // 5·1.10·20
    expect(central.upside).toBeCloseTo(0.10, 6);
    const cons = r.scenarios.find((s) => s.key === "conservador")!;
    const fav = r.scenarios.find((s) => s.key === "favorable")!;
    expect(cons.fairValue).toBeLessThan(central.fairValue);
    expect(fav.fairValue).toBeGreaterThan(central.fairValue);
    expect(r.sensitivity.length).toBe(4);
  });

  it("acota crecimientos extremos (200% -> 35%)", () => {
    const r = valuateCompany(input({ price: 100, f: payload({ pe_ttm: 10, eps_growth_yoy: 2.0 }) }));
    const central = r.scenarios.find((s) => s.key === "central")!;
    expect(central.fairValue).toBeCloseTo(10 * 1.35 * 10, 6); // eps=10, g acotado a 0.35
    expect(r.growthCentral).toBeCloseTo(0.35, 6);
  });
});

describe("valoración fundamental — disponibilidad y límites", () => {
  it("sin fundamentales -> no disponible y menciona EDGAR/extranjero", () => {
    const r = valuateCompany(input({ f: undefined }));
    expect(r.available).toBe(false);
    expect(r.unavailableReason!.toLowerCase()).toMatch(/edgar|extranjero/);
  });

  it("sin precio -> no disponible", () => {
    const r = valuateCompany(input({ price: null, f: payload({ pe_ttm: 20 }) }));
    expect(r.available).toBe(false);
  });

  it("P/E no positivo (pérdidas) pero con FCF yield -> método de respaldo", () => {
    const r = valuateCompany(input({ price: 50, f: payload({ pe_ttm: -5, fcf_yield: 0.04 }) }));
    expect(r.available).toBe(true);
    expect(r.method).toBe("fcf_fallback");
    expect(r.quality).toBe("baja");
  });

  it("P/E no positivo y sin FCF -> no disponible con motivo de pérdidas", () => {
    const r = valuateCompany(input({ price: 50, f: payload({ pe_ttm: -5 }) }));
    expect(r.available).toBe(false);
    expect(r.unavailableReason!.toLowerCase()).toContain("pérdidas");
  });

  it("escenarios no se presentan como probabilidades (etiqueta en limitaciones)", () => {
    const r = valuateCompany(input({ price: 100, f: payload({ pe_ttm: 20, eps_growth_yoy: 0.1 }) }));
    expect(r.limitations.join(" ").toLowerCase()).toContain("no son percentiles");
  });
});
