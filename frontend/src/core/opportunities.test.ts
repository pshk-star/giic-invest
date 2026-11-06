// Pruebas del motor de OPORTUNIDADES (vitest, CI). Verifican los puntos de la
// corrección del Advisor: score alto NO activa COMPRAR; COMPRAR exige valoración
// favorable + calidad alta + espacio de concentración; ESPERAR cuando hay valoración
// pero sin margen; INVESTIGAR sin datos / calidad baja; montos por convicción (no
// reparto igual); liquidez conservada (no se fuerza el presupuesto); A/B/C no se usan.
import { describe, expect, it } from "vitest";
import { buildOpportunities, type OpportunityInput } from "./opportunities";
import type { CompanyValuation, FundScenario } from "./fundamental";

const scen = (cons: number, central: number, fav: number): FundScenario[] => [
  { key: "conservador", label: "Conservador", fairValue: 100 * (1 + cons), upside: cons },
  { key: "central", label: "Central", fairValue: 100 * (1 + central), upside: central },
  { key: "favorable", label: "Favorable", fairValue: 100 * (1 + fav), upside: fav },
];

const val = (
  over: Partial<CompanyValuation> & { consUp?: number; centralUp?: number; favUp?: number } = {},
): CompanyValuation => {
  const { consUp = -0.05, centralUp = 0.05, favUp = 0.2, ...rest } = over;
  return {
    ticker: "X", name: "X", sector: "Tech", price: 100, priceAsOf: "2026-11-05",
    available: true, method: "pe_eps", horizonLabel: "12m", epsTtm: 5, peUsed: 20,
    growthCentral: centralUp, scenarios: scen(consUp, centralUp, favUp), sensitivity: [],
    quality: "alta", dataSources: ["EDGAR"], limitations: [], unavailableReason: null,
    ...rest,
  };
};

const inp = (over: Partial<OpportunityInput> = {}): OpportunityInput => ({
  ticker: "X", name: "X", sector: "Tech", composite: 50, price: 100, priceAsOf: "2026-11-05",
  valuation: val(), roe: 0.2, netMargin: 0.2, heldWeight: 0, effectiveWeight: null, ...over,
});

describe("clasificación COMPRAR / ESPERAR / INVESTIGAR", () => {
  it("un score alto NO basta para COMPRAR si la valoración no es favorable", () => {
    const r = buildOpportunities(
      [inp({ ticker: "HIGH", composite: 95, valuation: val({ consUp: -0.1, centralUp: 0.04, favUp: 0.15 }) })],
      3000, 10000, 0.25,
    );
    const d = r.decisions[0];
    expect(d.action).toBe("ESPERAR");
    expect(d.suggestedAmountUsd).toBeNull();
  });

  it("COMPRAR cuando el descuento central ≥15%, conservador positivo, calidad alta y hay espacio", () => {
    const r = buildOpportunities(
      [inp({ ticker: "BUY", composite: 40, valuation: val({ consUp: 0.03, centralUp: 0.22, favUp: 0.4 }) })],
      3000, 10000, 0.25,
    );
    const d = r.decisions.find((x) => x.ticker === "BUY")!;
    expect(d.action).toBe("COMPRAR");
    expect(d.suggestedAmountUsd).toBeGreaterThan(0);
    expect(d.evidenceForBuyingNow.length).toBeGreaterThan(0);
  });

  it("ESPERAR cuando hay valoración pero el conservador NO es positivo aunque el central ≥15%", () => {
    const r = buildOpportunities(
      [inp({ valuation: val({ consUp: -0.02, centralUp: 0.18, favUp: 0.35 }) })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("ESPERAR");
  });

  it("INVESTIGAR cuando no hay valoración disponible", () => {
    const r = buildOpportunities(
      [inp({ valuation: { ...val(), available: false, unavailableReason: "Sin fundamentales EDGAR" } })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("INVESTIGAR");
    expect(r.decisions[0].missing.length).toBeGreaterThan(0);
  });

  it("INVESTIGAR cuando la calidad de los datos es baja (p. ej. desactualizada)", () => {
    const r = buildOpportunities(
      [inp({ valuation: val({ quality: "baja", consUp: 0.05, centralUp: 0.25 }) })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("INVESTIGAR");
  });

  it("calidad alta pero sin espacio de concentración → NO COMPRAR (ESPERAR)", () => {
    const r = buildOpportunities(
      [inp({ heldWeight: 0.25, valuation: val({ consUp: 0.05, centralUp: 0.25, favUp: 0.45 }) })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("ESPERAR");
  });
});

describe("montos por convicción, no reparto igual", () => {
  it("reparte más al de mayor descuento central y NO a partes iguales", () => {
    const r = buildOpportunities(
      [
        inp({ ticker: "A", valuation: val({ consUp: 0.02, centralUp: 0.40, favUp: 0.6 }) }),
        inp({ ticker: "B", valuation: val({ consUp: 0.02, centralUp: 0.16, favUp: 0.3 }) }),
      ],
      3000, 100000, 0.25,
    );
    const a = r.decisions.find((x) => x.ticker === "A")!;
    const b = r.decisions.find((x) => x.ticker === "B")!;
    expect(a.action).toBe("COMPRAR");
    expect(b.action).toBe("COMPRAR");
    expect(a.suggestedAmountUsd!).toBeGreaterThan(b.suggestedAmountUsd!);
    // No es el reparto igual 1500/1500 del motor anterior.
    expect(a.suggestedAmountUsd).not.toBe(b.suggestedAmountUsd);
  });

  it("el tope de concentración limita el monto y el resto queda en liquidez", () => {
    // portfolio chico: 25% de (1000+3000)=1000 USD de techo por activo.
    const r = buildOpportunities(
      [inp({ ticker: "A", heldWeight: 0, valuation: val({ consUp: 0.05, centralUp: 0.5, favUp: 0.7 }) })],
      3000, 1000, 0.25,
    );
    const a = r.decisions[0];
    expect(a.action).toBe("COMPRAR");
    expect(a.suggestedAmountUsd!).toBeLessThanOrEqual(1000);
    expect(r.cashKept).toBeGreaterThanOrEqual(2000);
  });
});

describe("liquidez y ausencia de compra forzada", () => {
  it("si ninguna candidata califica, NO se despliega capital y la liquidez se mantiene", () => {
    const r = buildOpportunities(
      [
        inp({ ticker: "A", composite: 90, valuation: val({ consUp: -0.1, centralUp: 0.05 }) }),
        inp({ ticker: "B", composite: 85, valuation: { ...val(), available: false, unavailableReason: "n/d" } }),
      ],
      3000, 10000, 0.25,
    );
    expect(r.deployed).toBe(0);
    expect(r.cashKept).toBe(3000);
    expect(r.note).toContain("liquidez");
    expect(r.decisions.every((d) => d.action !== "COMPRAR")).toBe(true);
  });

  it("no se fuerza a gastar todo el presupuesto aunque haya una COMPRAR modesta", () => {
    const r = buildOpportunities(
      [inp({ ticker: "A", valuation: val({ consUp: 0.01, centralUp: 0.16, favUp: 0.25 }) })],
      3000, 100000, 0.25,
    );
    const a = r.decisions[0];
    expect(a.action).toBe("COMPRAR");
    // convicción 16% → monto acotado, no los 3000 completos.
    expect(a.suggestedAmountUsd!).toBeLessThanOrEqual(3000);
  });
});

describe("distingue buena empresa de oportunidad real", () => {
  it("buena empresa (ROE/margen altos) con precio sin margen sigue siendo ESPERAR", () => {
    const r = buildOpportunities(
      [inp({ roe: 0.35, netMargin: 0.3, valuation: val({ consUp: -0.05, centralUp: 0.03 }) })],
      3000, 10000, 0.25,
    );
    const d = r.decisions[0];
    expect(d.action).toBe("ESPERAR");
    expect(d.businessQuality).toBe("buena");
  });
});
