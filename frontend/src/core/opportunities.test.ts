// Pruebas del motor de OPORTUNIDADES (vitest, CI) — tras la auditoría de circularidad.
// Verifican: COMPRAR se dispara por la señal de valor NO circular (rendimiento reportado
// vs retorno exigido), NO por el crecimiento proyectado; cíclicos no son COMPRAR;
// brecha de datos → INVESTIGAR (no veredicto); montos por convicción (exceso de rendimiento),
// no reparto igual; liquidez conservada; sin compra forzada.
import { describe, expect, it } from "vitest";
import { buildOpportunities, type OpportunityInput } from "./opportunities";
import type { CompanyValuation, FundScenario } from "./fundamental";

// scenarios sólo aportan la proyección 12m circular (contexto); la decisión NO depende de ella.
const scen = (central: number): FundScenario[] => [
  { key: "conservador", label: "Conservador", fairValue: 100, upside: central - 0.1, assumptions: [] },
  { key: "central", label: "Central", fairValue: 100 * (1 + central), upside: central, assumptions: [] },
  { key: "favorable", label: "Favorable", fairValue: 120, upside: central + 0.2, assumptions: [] },
];

const val = (over: Partial<CompanyValuation> = {}): CompanyValuation => ({
  ticker: "X", name: "X", sector: "Tech", price: 100, priceAsOf: "2026-11-05",
  available: true, method: "pe_eps", horizonLabel: "12m", epsTtm: 5, peUsed: 20,
  growthCentral: 0.1, scenarios: scen(0.1), sensitivity: [], quality: "alta",
  dataSources: [], limitations: [], unavailableReason: null,
  epsReported: 10, earningsYield: 0.10, fcfYield: null, requiredReturn: 0.07,
  yieldVerdict: "atractivo", cyclical: false, cyclicalNote: null,
  priceAnchored: true, decisionBasis: "test",
  ...over,
});

const inp = (over: Partial<OpportunityInput> = {}): OpportunityInput => ({
  ticker: "X", name: "X", sector: "Tech", composite: 50, price: 100, priceAsOf: "2026-11-05",
  valuation: val(), roe: 0.2, netMargin: 0.2, heldWeight: 0, effectiveWeight: null, ...over,
});

describe("COMPRAR se decide por rendimiento NO circular, no por crecimiento proyectado", () => {
  it("un crecimiento proyectado alto NO basta para COMPRAR si el rendimiento no es atractivo", () => {
    // central upside 35% (proyección circular alta) pero rendimiento 'caro' → ESPERAR.
    const r = buildOpportunities(
      [inp({ composite: 95, valuation: val({ scenarios: scen(0.35), growthCentral: 0.35,
        earningsYield: 0.03, yieldVerdict: "caro" }) })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("ESPERAR");
    expect(r.decisions[0].suggestedAmountUsd).toBeNull();
  });

  it("COMPRAR cuando el rendimiento reportado supera el exigido con margen, calidad alta, no cíclico", () => {
    const r = buildOpportunities(
      [inp({ ticker: "BUY", composite: 40, valuation: val({ earningsYield: 0.11, yieldVerdict: "atractivo",
        scenarios: scen(0.04), growthCentral: 0.04 }) })],   // proyección circular BAJA, da igual
      3000, 10000, 0.25,
    );
    const d = r.decisions.find((x) => x.ticker === "BUY")!;
    expect(d.action).toBe("COMPRAR");
    expect(d.suggestedAmountUsd).toBeGreaterThan(0);
    expect(d.evidenceForBuyingNow.join(" ")).toContain("endimiento");
  });

  it("rendimiento sólo 'razonable' (iguala pero no supera el exigido) → ESPERAR", () => {
    const r = buildOpportunities(
      [inp({ valuation: val({ earningsYield: 0.072, yieldVerdict: "razonable" }) })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("ESPERAR");
  });
});

describe("cíclicos y beneficios extraordinarios", () => {
  it("beneficio cíclico/extraordinario NO es COMPRAR aunque el rendimiento parezca atractivo", () => {
    const r = buildOpportunities(
      [inp({ valuation: val({ earningsYield: 0.12, yieldVerdict: "atractivo", cyclical: true,
        cyclicalNote: "pico cíclico" }) })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("ESPERAR");
  });
});

describe("brecha de datos → INVESTIGAR, no veredicto de inversión", () => {
  it("sin valoración disponible → INVESTIGAR y lo declara como brecha de datos", () => {
    const r = buildOpportunities(
      [inp({ valuation: { ...val(), available: false, unavailableReason: "Sin EPS en EDGAR" } })],
      3000, 10000, 0.25,
    );
    const d = r.decisions[0];
    expect(d.action).toBe("INVESTIGAR");
    expect(d.valuationLine.toLowerCase()).toContain("brecha de datos");
  });

  it("calidad de datos baja → INVESTIGAR (no COMPRAR aunque el rendimiento sea alto)", () => {
    const r = buildOpportunities(
      [inp({ valuation: val({ quality: "baja", earningsYield: 0.15, yieldVerdict: "atractivo" }) })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("INVESTIGAR");
  });

  it("sin precio → INVESTIGAR", () => {
    const r = buildOpportunities(
      [inp({ price: null, valuation: { ...val(), price: null, available: false, unavailableReason: "sin precio" } })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("INVESTIGAR");
  });
});

describe("concentración", () => {
  it("rendimiento atractivo pero sin espacio → ESPERAR", () => {
    const r = buildOpportunities(
      [inp({ heldWeight: 0.25, valuation: val({ earningsYield: 0.12, yieldVerdict: "atractivo" }) })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("ESPERAR");
  });
});

describe("montos por convicción (exceso de rendimiento), no reparto igual", () => {
  it("reparte más al de mayor exceso de rendimiento sobre el exigido", () => {
    const r = buildOpportunities(
      [
        inp({ ticker: "A", valuation: val({ earningsYield: 0.14, yieldVerdict: "atractivo" }) }), // exceso 100%
        inp({ ticker: "B", valuation: val({ earningsYield: 0.084, yieldVerdict: "atractivo" }) }), // exceso 20%
      ],
      3000, 100000, 0.25,
    );
    const a = r.decisions.find((x) => x.ticker === "A")!;
    const b = r.decisions.find((x) => x.ticker === "B")!;
    expect(a.action).toBe("COMPRAR");
    expect(b.action).toBe("COMPRAR");
    expect(a.suggestedAmountUsd!).toBeGreaterThan(b.suggestedAmountUsd!);
    expect(a.suggestedAmountUsd).not.toBe(b.suggestedAmountUsd);
  });

  it("el tope de concentración limita el monto; el resto queda en liquidez", () => {
    const r = buildOpportunities(
      [inp({ ticker: "A", valuation: val({ earningsYield: 0.20, yieldVerdict: "atractivo" }) })],
      3000, 1000, 0.25,   // techo por activo = 25% de (1000+3000) = 1000
    );
    const a = r.decisions[0];
    expect(a.action).toBe("COMPRAR");
    expect(a.suggestedAmountUsd!).toBeLessThanOrEqual(1000);
    expect(r.cashKept).toBeGreaterThanOrEqual(2000);
  });
});

describe("liquidez y ausencia de compra forzada", () => {
  it("si ninguna candidata califica, no se despliega capital y la liquidez se mantiene", () => {
    const r = buildOpportunities(
      [
        inp({ ticker: "A", valuation: val({ earningsYield: 0.03, yieldVerdict: "caro" }) }),
        inp({ ticker: "B", valuation: { ...val(), available: false, unavailableReason: "n/d" } }),
      ],
      3000, 10000, 0.25,
    );
    expect(r.deployed).toBe(0);
    expect(r.cashKept).toBe(3000);
    expect(r.note).toContain("liquidez");
  });
});
