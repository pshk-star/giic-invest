import { describe, expect, it } from "vitest";
import { aggregateFundamental, valuateCompany, type AggItem, type FundamentalInput } from "./fundamental";
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

describe("agregación fundamental a cartera (coherente por escenario)", () => {
  const sc = (central: number) => [
    { key: "conservador" as const, label: "C", fairValue: central * 0.8, upside: 0, assumptions: [] },
    { key: "central" as const, label: "Central", fairValue: central, upside: 0, assumptions: [] },
    { key: "favorable" as const, label: "F", fairValue: central * 1.2, upside: 0, assumptions: [] },
  ];
  const items: AggItem[] = [
    { marketValue: 1000, price: 100, scenarios: sc(110) }, // factor 1.1 -> 1100
    { marketValue: 2000, price: 50, scenarios: sc(55) },   // factor 1.1 -> 2200
  ];

  it("suma por escenario coherente + no cubierto a valor actual; cobertura explícita", () => {
    const a = aggregateFundamental(items, 1000);
    expect(a.totalCurrent).toBe(4000);
    expect(a.coveredCurrent).toBe(3000);
    expect(a.uncoveredCurrent).toBe(1000);
    expect(a.coveragePct).toBeCloseTo(0.75, 6);
    const central = a.perScenario.find((p) => p.key === "central")!;
    expect(central.value).toBeCloseTo(4300, 6);      // 1100 + 2200 + 1000
    expect(central.upside).toBeCloseTo(0.075, 6);
  });

  it("la parte no cubierta no se proyecta (se mantiene constante) y tiene sensibilidad propia", () => {
    const a = aggregateFundamental(items, 1000);
    expect(a.sensitivityUncovered.length).toBe(2);
    // central cubierto = 3300; ±10% sobre 1000 -> 4200 y 4400
    expect(a.sensitivityUncovered[0].value).toBeCloseTo(4200, 6);
    expect(a.sensitivityUncovered[1].value).toBeCloseTo(4400, 6);
  });

  it("cartera sin posiciones cubiertas: cobertura 0, no extrapola", () => {
    const a = aggregateFundamental([], 5000);
    expect(a.coveragePct).toBe(0);
    expect(a.perScenario.every((p) => p.value === 5000)).toBe(true);
  });
});

describe("antigüedad de fundamentales", () => {
  it("fundamentales viejos (>18m) degradan la calidad a baja", () => {
    const r = valuateCompany(input({ price: 100, priceAsOf: "2026-11-01", f: payload({ pe_ttm: 20, eps_growth_yoy: 0.1, as_of: "2024-01-01" }) }));
    expect(r.available).toBe(true);
    expect(r.quality).toBe("baja");
    expect(r.limitations.join(" ").toLowerCase()).toContain("antigüedad");
  });
  it("fundamentales recientes conservan calidad alta", () => {
    const r = valuateCompany(input({ price: 100, priceAsOf: "2026-11-01", f: payload({ pe_ttm: 20, eps_growth_yoy: 0.1, as_of: "2026-03-31" }) }));
    expect(r.quality).toBe("alta");
  });
});
