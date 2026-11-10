import { describe, expect, it } from "vitest";
import { buildAdvice2, type Advisor2Input, type FvSummary } from "./advisor2";
import type { Holding } from "./advisor";

const C = { maxWeightAsset: 0.25, maxWeightSector: 0.4 };
function hold(ticker: string, mv: number, weight: number, sector = "Technology", assetClass = "equity"): Holding {
  return { ticker, name: ticker, sector, assetClass, marketValue: mv, weight, priceAsOf: "2026-11-06" };
}
function etf(ticker: string, mv: number, weight: number): Holding {
  return { ticker, name: ticker, sector: null, assetClass: "etf", marketValue: mv, weight, priceAsOf: "2026-11-06" };
}
function fv(over: Partial<FvSummary>): FvSummary {
  return { available: true, priceComparable: true, marginBase: 0, marginConservative: null, marginOptimista: null, confidence: "Media", currency: "USD", ...over };
}
function base(over: Partial<Advisor2Input>): Advisor2Input {
  return { holdings: [], scan: [], cash: 3000, constraints: C, fv: {}, scanAsOf: "2026-11-09", ...over };
}
const recOf = (r: ReturnType<typeof buildAdvice2>, t: string) => r.recommendations.find((x) => x.ticker === t)!;

describe("advisor2.2 — dos decisiones separadas (posición vs aporte)", () => {
  it("SCHD: MANTENER la posición y ACUMULAR con el aporte (no es contradictorio)", () => {
    const r = buildAdvice2(base({
      holdings: [hold("NVDA", 20000, 0.6, "Technology"), etf("SCHD", 4000, 0.12)], cash: 3000,
      scan: [{ ticker: "NVDA", sector: "Technology", composite: 58 }],
      fv: { NVDA: fv({ marginBase: -0.5 }) },
      effBefore: { effN: 12.8, hhi: 0.078, tech: 0.153 },
      etfRoutes: [{ ticker: "SCHD", currentValue: 4000, effNamesAfter: 14.9, hhiAfter: 0.067, techAfter: 0.148 }],
    }));
    const schd = recOf(r, "SCHD");
    expect(schd.positionAction).toBe("MANTENER");
    expect(schd.contribAction).toBe("ACUMULAR");
    expect(schd.contribAmount).toBeGreaterThan(0);
    expect(r.allocation.some((a) => a.ticker === "SCHD")).toBe(true);
  });

  it("aporte por DIVERSIFICACIÓN es PARCIAL (50%) con liquidez residual", () => {
    const r = buildAdvice2(base({
      holdings: [hold("NVDA", 20000, 0.6, "Technology"), etf("SCHD", 4000, 0.12)], cash: 3000,
      scan: [{ ticker: "NVDA", sector: "Technology", composite: 58 }],
      fv: { NVDA: fv({ marginBase: -0.5 }) },
      effBefore: { effN: 12.8, hhi: 0.078, tech: 0.153 },
      etfRoutes: [{ ticker: "SCHD", currentValue: 4000, effNamesAfter: 14.9, hhiAfter: 0.067, techAfter: 0.148 }],
    }));
    expect(r.invested).toBe(1500);
    expect(r.cashKept).toBe(1500);
    expect(r.invested + r.cashKept).toBe(3000);
  });

  it("aporte por VALORACIÓN (infravalorada) es COMPLETO (100%)", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 2000, 0.1), hold("BBB", 18000, 0.9, "Health")], cash: 3000,
      scan: [{ ticker: "AAA", sector: "Tech", composite: 70 }, { ticker: "BBB", sector: "Health", composite: 45 }],
      fv: { AAA: fv({ marginBase: 0.25, confidence: "Alta" }), BBB: fv({ marginBase: 0 }) },
    }));
    expect(recOf(r, "AAA").contribAction).toBe("ACUMULAR");
    expect(r.invested).toBe(3000);
    expect(r.cashKept).toBe(0);
  });
});

describe("advisor2.2 — todas las acciones de POSICIÓN son alcanzables", () => {
  it("VENDER: posición ínfima", () => {
    const r = buildAdvice2(base({ holdings: [hold("AAA", 50, 0.005), hold("BBB", 10000, 0.995)], fv: {} }));
    expect(recOf(r, "AAA").positionAction).toBe("VENDER");
  });
  it("REDUCIR: peso por encima del límite", () => {
    const r = buildAdvice2(base({ holdings: [hold("AAA", 40000, 0.4)], fv: { AAA: fv({ marginBase: 0.3 }) } }));
    expect(recOf(r, "AAA").positionAction).toBe("REDUCIR");
  });
  it("REDUCIR: muy sobrevalorada + atractivo débil (<40)", () => {
    const r = buildAdvice2(base({ holdings: [hold("AAA", 5000, 0.1)], scan: [{ ticker: "AAA", sector: "Tech", composite: 30 }], fv: { AAA: fv({ marginBase: -0.3 }) } }));
    expect(recOf(r, "AAA").positionAction).toBe("REDUCIR");
  });
  it("MANTENER: valorada y dentro de límites (conclusión fundamentada)", () => {
    const r = buildAdvice2(base({ holdings: [hold("AAA", 5000, 0.1)], scan: [{ ticker: "AAA", sector: "Tech", composite: 60 }], fv: { AAA: fv({ marginBase: 0.0 }) } }));
    expect(recOf(r, "AAA").positionAction).toBe("MANTENER");
  });
  it("REVISAR (no MANTENER disfrazado): valoración no comparable por FX", () => {
    const r = buildAdvice2(base({ holdings: [hold("TSM", 5000, 0.1)], scan: [{ ticker: "TSM", sector: "Tech", composite: 57 }], fv: { TSM: fv({ priceComparable: false, marginBase: null, currency: "TWD" }) } }));
    expect(recOf(r, "TSM").positionAction).toBe("REVISAR");
  });
  it("REVISAR: sin Fair Value (financiera/insuf.)", () => {
    const r = buildAdvice2(base({ holdings: [hold("JPM", 5000, 0.1)], scan: [{ ticker: "JPM", sector: "Financials", composite: 60 }], fv: { JPM: { available: false, priceComparable: false, marginBase: null, marginConservative: null, marginOptimista: null, confidence: null, currency: "USD", reason: "banco" } } }));
    expect(recOf(r, "JPM").positionAction).toBe("REVISAR");
  });
});

describe("advisor2.2 — acciones de APORTE alcanzables y coherentes", () => {
  it("ACUMULAR: infravalorada+atractiva recibe aporte; ESPERAR: sobrevalorada no", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 2000, 0.1), hold("CCC", 5000, 0.25, "Health")], cash: 3000,
      scan: [{ ticker: "AAA", sector: "Tech", composite: 70 }, { ticker: "CCC", sector: "Health", composite: 50 }],
      fv: { AAA: fv({ marginBase: 0.2 }), CCC: fv({ marginBase: -0.4 }) },
    }));
    expect(recOf(r, "AAA").contribAction).toBe("ACUMULAR");
    expect(recOf(r, "CCC").contribAction).toBe("ESPERAR");
  });
  it("COMPRAR: oportunidad infravalorada fuera de cartera es elegible", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 10000, 1, "Tech")], cash: 3000,
      scan: [{ ticker: "ZZZ", sector: "Health", composite: 88 }], fv: { ZZZ: fv({ marginBase: 0.2 }) },
    }));
    const opp = r.opportunities.find((o) => o.ticker === "ZZZ")!;
    expect(opp.action).toBe("COMPRAR");
    expect(opp.eligible).toBe(true);
    expect(r.allocation.some((a) => a.ticker === "ZZZ")).toBe(true);
  });
  it("margen implausible ⇒ posición REVISAR y aporte ESPERAR (no compra)", () => {
    const r = buildAdvice2(base({ holdings: [hold("EOG", 2000, 0.1)], cash: 3000, scan: [{ ticker: "EOG", sector: "Energy", composite: 79 }], fv: { EOG: fv({ marginBase: 2.0 }) } }));
    expect(recOf(r, "EOG").positionAction).toBe("REVISAR");
    expect(recOf(r, "EOG").contribAction).toBe("ESPERAR");
    expect(r.invested).toBe(0);
  });
});

describe("advisor2.2 — asignación, rutas y efectivo justificado", () => {
  it("ETF que sube tecnología NO entra como diversificador; sin nada más ⇒ todo liquidez", () => {
    const r = buildAdvice2(base({
      holdings: [hold("NVDA", 10000, 1, "Technology")], cash: 3000,
      scan: [{ ticker: "NVDA", sector: "Technology", composite: 58 }], fv: { NVDA: fv({ marginBase: -0.5 }) },
      effBefore: { effN: 12.8, hhi: 0.078, tech: 0.153 },
      etfRoutes: [{ ticker: "QQQ", currentValue: 5000, effNamesAfter: 12.7, hhiAfter: 0.079, techAfter: 0.20 }],
    }));
    expect(r.routes.find((x) => x.id === "C")!.available).toBe(false);
    expect(r.invested).toBe(0);
    expect(r.stance).toBe("esperar");
  });
  it("comparación de rutas A/B/C/D siempre presente y suma exacta", () => {
    const r = buildAdvice2(base({ holdings: [hold("AAA", 10000, 1)], scan: [], fv: {} }));
    expect(r.routes.map((x) => x.id).sort()).toEqual(["A", "B", "C", "D"]);
    expect(r.invested + r.cashKept).toBe(3000);
  });
});
