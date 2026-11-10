import { describe, expect, it } from "vitest";
import { buildAdvice2, type Advisor2Input, type FvSummary } from "./advisor2";
import type { Holding } from "./advisor";

const C = { maxWeightAsset: 0.25, maxWeightSector: 0.4 };
function hold(ticker: string, mv: number, weight: number, sector = "Technology"): Holding {
  return { ticker, name: ticker, sector, assetClass: "equity", marketValue: mv, weight, priceAsOf: "2026-11-06" };
}
function fv(over: Partial<FvSummary>): FvSummary {
  return { available: true, priceComparable: true, marginBase: 0, marginConservative: null, marginOptimista: null, confidence: "Media", currency: "USD", ...over };
}
function base(over: Partial<Advisor2Input>): Advisor2Input {
  return { holdings: [], scan: [], cash: 3000, constraints: C, fv: {}, scanAsOf: "2026-11-09", ...over };
}

describe("buildAdvice2 — asignación exacta y efectivo", () => {
  it("la suma de asignaciones + efectivo retenido = capital exactamente", () => {
    const holdings = [hold("AAA", 10000, 0.33), hold("BBB", 20000, 0.67)];
    const r = buildAdvice2(base({
      holdings, cash: 3000,
      scan: [{ ticker: "AAA", sector: "Tech", composite: 70 }, { ticker: "BBB", sector: "Tech", composite: 72 }, { ticker: "CCC", sector: "Health", composite: 80 }],
      fv: { AAA: fv({ marginBase: 0.15 }), BBB: fv({ marginBase: 0.12 }), CCC: fv({ marginBase: 0.18 }) },
    }));
    expect(r.invested + r.cashKept).toBe(3000);
    expect(r.allocation.reduce((a, x) => a + x.amount, 0)).toBe(r.invested);
  });

  it("sin candidatas convergentes ⇒ ESPERAR y todo el efectivo retenido", () => {
    const holdings = [hold("AAA", 10000, 1)];
    const r = buildAdvice2(base({
      holdings, cash: 3000,
      scan: [{ ticker: "AAA", sector: "Tech", composite: 30 }],   // atractivo débil
      fv: { AAA: fv({ marginBase: -0.30 }) },                      // sobrevalorada
    }));
    expect(r.invested).toBe(0);
    expect(r.cashKept).toBe(3000);
    expect(r.stance).toBe("esperar");
  });
});

describe("buildAdvice2 — convergencia de evidencia (no un solo DCF)", () => {
  it("infravalorada + atractivo suficiente ⇒ ACUMULAR y elegible para asignación", () => {
    // AAA con espacio bajo el tope por activo (1000 de una cartera de 10000 + 3000 aporte).
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 1000, 0.1), hold("BBB", 9000, 0.9, "Health")], cash: 3000,
      scan: [{ ticker: "AAA", sector: "Tech", composite: 60 }, { ticker: "BBB", sector: "Health", composite: 50 }],
      fv: { AAA: fv({ marginBase: 0.2, confidence: "Alta" }), BBB: fv({ marginBase: 0 }) },
    }));
    const rec = r.recommendations.find((x) => x.ticker === "AAA")!;
    expect(rec.action).toBe("ACUMULAR");
    expect(r.allocation.some((a) => a.ticker === "AAA")).toBe(true);
  });

  it("infravalorada pero atractivo DÉBIL ⇒ MANTENER (no compra por un solo DCF)", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 5000, 0.1)], cash: 3000,
      scan: [{ ticker: "AAA", sector: "Tech", composite: 20 }],
      fv: { AAA: fv({ marginBase: 0.25 }) },
    }));
    const rec = r.recommendations.find((x) => x.ticker === "AAA")!;
    expect(rec.action).toBe("MANTENER");
    expect(r.invested).toBe(0);
  });

  it("muy sobrevalorada + atractivo DÉBIL (<40) ⇒ REDUCIR (parcial)", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 5000, 0.1)],
      scan: [{ ticker: "AAA", sector: "Tech", composite: 30 }],
      fv: { AAA: fv({ marginBase: -0.3 }) },
    }));
    expect(r.recommendations.find((x) => x.ticker === "AAA")!.action).toBe("REDUCIR");
  });

  it("muy sobrevalorada pero atractivo MEDIO (no débil) ⇒ MANTENER (no recorte por un solo DCF)", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 5000, 0.1)],
      scan: [{ ticker: "AAA", sector: "Tech", composite: 55 }],
      fv: { AAA: fv({ marginBase: -0.3 }) },
    }));
    expect(r.recommendations.find((x) => x.ticker === "AAA")!.action).toBe("MANTENER");
  });

  it("muy sobrevalorada pero atractivo FUERTE ⇒ MANTENER (no venta por un solo DCF)", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 5000, 0.1)],
      scan: [{ ticker: "AAA", sector: "Tech", composite: 80 }],
      fv: { AAA: fv({ marginBase: -0.3 }) },
    }));
    expect(r.recommendations.find((x) => x.ticker === "AAA")!.action).toBe("MANTENER");
  });
});

describe("buildAdvice2 — abstención, riesgo e higiene", () => {
  it("sin Fair Value ⇒ MANTENER prudente y NO elegible para compra", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 5000, 0.1)], cash: 3000,
      scan: [{ ticker: "AAA", sector: "Tech", composite: 90 }],
      fv: { AAA: { available: false, priceComparable: false, marginBase: null, marginConservative: null, marginOptimista: null, confidence: null, currency: "USD", reason: "banco" } },
    }));
    expect(r.recommendations.find((x) => x.ticker === "AAA")!.action).toBe("MANTENER");
    expect(r.invested).toBe(0);
  });

  it("Fair Value no comparable (FX) ⇒ no usable para decidir compra", () => {
    const r = buildAdvice2(base({
      holdings: [hold("TSM", 5000, 0.1)], cash: 3000,
      scan: [{ ticker: "TSM", sector: "Tech", composite: 85 }],
      fv: { TSM: fv({ priceComparable: false, marginBase: null, currency: "TWD" }) },
    }));
    expect(["MANTENER"]).toContain(r.recommendations.find((x) => x.ticker === "TSM")!.action);
    expect(r.invested).toBe(0);
  });

  it("peso por encima del límite ⇒ REDUCIR aunque esté infravalorada", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 40000, 0.4)],
      scan: [{ ticker: "AAA", sector: "Tech", composite: 70 }],
      fv: { AAA: fv({ marginBase: 0.3 }) },
    }));
    const rec = r.recommendations.find((x) => x.ticker === "AAA")!;
    expect(rec.action).toBe("REDUCIR");
    expect(rec.penalize.join(" ")).toMatch(/infravalorada|peso/i);
  });

  it("posición ínfima ⇒ VENDER (higiene)", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 50, 0.005), hold("BBB", 10000, 0.995)],
      scan: [], fv: {},
    }));
    expect(r.recommendations.find((x) => x.ticker === "AAA")!.action).toBe("VENDER");
  });
});

describe("buildAdvice2 — guarda de margen implausible (artefacto del DCF)", () => {
  it("margen al alza desmesurado (+200%) ⇒ MANTENER y NO compra", () => {
    const r = buildAdvice2(base({
      holdings: [hold("EOG", 2000, 0.1)], cash: 3000,
      scan: [{ ticker: "EOG", sector: "Energy", composite: 79 }],
      fv: { EOG: fv({ marginBase: 2.0 }) },
    }));
    expect(r.recommendations.find((x) => x.ticker === "EOG")!.action).toBe("MANTENER");
    expect(r.invested).toBe(0);
  });
  it("candidata con margen implausible ⇒ INVESTIGAR (no elegible)", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 10000, 1)], cash: 3000,
      scan: [{ ticker: "EOG", sector: "Energy", composite: 79 }],
      fv: { EOG: fv({ marginBase: 2.0 }) },
    }));
    const opp = r.opportunities.find((o) => o.ticker === "EOG")!;
    expect(opp.action).toBe("INVESTIGAR");
    expect(opp.eligible).toBe(false);
  });
});

describe("buildAdvice2 — ruta ETF diversificada (2.1) y graduación", () => {
  it("ETF que reduce la concentración efectiva ⇒ ruta C elegida y aporte asignado", () => {
    const r = buildAdvice2(base({
      holdings: [hold("NVDA", 10000, 0.5, "Technology"), { ticker: "SCHD", name: "SCHD", sector: null, assetClass: "etf", marketValue: 4000, weight: 0.2, priceAsOf: "2026-11-06" }], cash: 3000,
      scan: [{ ticker: "NVDA", sector: "Technology", composite: 58 }],
      fv: { NVDA: fv({ marginBase: -0.5 }) },
      effBefore: { effN: 12.8, hhi: 0.078, tech: 0.153 },
      etfRoutes: [{ ticker: "SCHD", currentValue: 4000, effNamesAfter: 14.9, hhiAfter: 0.067, techAfter: 0.148 }],
    }));
    expect(r.invested).toBe(3000);
    expect(r.allocation.some((a) => a.ticker === "SCHD" && a.route === "C")).toBe(true);
    expect(r.routes.find((x) => x.id === "C")!.chosen).toBe(true);
    expect(r.invested + r.cashKept).toBe(3000);
  });

  it("ETF que NO mejora diversificación ⇒ ruta C no disponible; si nada más, ESPERAR", () => {
    const r = buildAdvice2(base({
      holdings: [hold("NVDA", 10000, 1, "Technology")], cash: 3000,
      scan: [{ ticker: "NVDA", sector: "Technology", composite: 58 }],
      fv: { NVDA: fv({ marginBase: -0.5 }) },
      effBefore: { effN: 12.8, hhi: 0.078, tech: 0.153 },
      etfRoutes: [{ ticker: "QQQ", currentValue: 5000, effNamesAfter: 12.7, hhiAfter: 0.079, techAfter: 0.192 }], // sube concentración
    }));
    expect(r.routes.find((x) => x.id === "C")!.available).toBe(false);
    expect(r.invested).toBe(0);
    expect(r.stance).toBe("esperar");
  });

  it("razonablemente valorada (margen ~0) + atractivo sólido ⇒ ACUMULAR graduado", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 1000, 0.1), hold("BBB", 9000, 0.9, "Health")], cash: 3000,
      scan: [{ ticker: "AAA", sector: "Tech", composite: 62 }],
      fv: { AAA: fv({ marginBase: 0.02, confidence: "Media" }) },  // dentro de ±10%
    }));
    expect(r.recommendations.find((x) => x.ticker === "AAA")!.action).toBe("ACUMULAR");
  });

  it("comparación de rutas A/B/C/D siempre presente", () => {
    const r = buildAdvice2(base({ holdings: [hold("AAA", 10000, 1)], scan: [], fv: {} }));
    expect(r.routes.map((x) => x.id).sort()).toEqual(["A", "B", "C", "D"]);
  });
});

describe("buildAdvice2 — oportunidades fuera de cartera", () => {
  it("candidata fuerte sin Fair Value ⇒ INVESTIGAR (no elegible)", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 10000, 1)], cash: 3000,
      scan: [{ ticker: "ZZZ", sector: "Health", composite: 88 }],
      fv: { ZZZ: { available: false, priceComparable: false, marginBase: null, marginConservative: null, marginOptimista: null, confidence: null, currency: "USD" } },
    }));
    const opp = r.opportunities.find((o) => o.ticker === "ZZZ")!;
    expect(opp.action).toBe("INVESTIGAR");
    expect(opp.eligible).toBe(false);
    expect(r.invested).toBe(0);
  });

  it("candidata fuerte e infravalorada ⇒ COMPRAR (elegible) y entra en asignación", () => {
    const r = buildAdvice2(base({
      holdings: [hold("AAA", 10000, 1, "Tech")], cash: 3000,
      scan: [{ ticker: "ZZZ", sector: "Health", composite: 88 }],
      fv: { ZZZ: fv({ marginBase: 0.2 }) },
    }));
    const opp = r.opportunities.find((o) => o.ticker === "ZZZ")!;
    expect(opp.action).toBe("COMPRAR");
    expect(opp.eligible).toBe(true);
    expect(r.allocation.some((a) => a.ticker === "ZZZ")).toBe(true);
  });
});
