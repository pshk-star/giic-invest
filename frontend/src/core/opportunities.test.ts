// Pruebas del motor de SEÑALES de oportunidad (vitest, CI) — tras degradar la criba.
// Verifican: NO se emite COMPRAR (no hay valoración fundada); con datos → EN OBSERVACIÓN
// (ESPERAR) como señal descriptiva sin monto; brecha de datos → INVESTIGAR; la alerta de
// ciclicidad se refleja; la liquidez se conserva íntegra; la nota aclara señal ≠ decisión.
import { describe, expect, it } from "vitest";
import { buildOpportunities, type OpportunityInput } from "./opportunities";
import type { CompanyValuation, FundScenario } from "./fundamental";

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
  epsReported: 10, earningsBasis: "reported_annual", ttmEps: null, normalizedEps: null, forwardEps: null,
  earningsYield: 0.10, fcfYield: null, referenceYield: 0.07, yieldVsReference: "encima",
  cyclicalAlert: false, cyclicalNote: null, epsConsistent: true, consistencyNotes: [],
  priceAnchored: true, decisionReady: false, decisionBlock: "sin valoración fundada", decisionBasis: "test",
  ...over,
});

const inp = (over: Partial<OpportunityInput> = {}): OpportunityInput => ({
  ticker: "X", name: "X", sector: "Tech", composite: 50, price: 100, priceAsOf: "2026-11-05",
  valuation: val(), roe: 0.2, netMargin: 0.2, heldWeight: 0, effectiveWeight: null, ...over,
});

describe("el motor NO emite decisiones de compra (sin valoración fundada)", () => {
  it("con rendimiento alto, calidad alta y no cíclico → EN OBSERVACIÓN (ESPERAR), NUNCA COMPRAR", () => {
    const r = buildOpportunities(
      [inp({ composite: 95, valuation: val({ earningsYield: 0.20, yieldVsReference: "encima" }) })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("ESPERAR");
    expect(r.decisions.some((d) => d.action === "COMPRAR")).toBe(false);
    expect(r.decisions[0].suggestedAmountUsd).toBeNull();
  });

  it("la decisión en observación muestra la señal descriptiva y por qué no es decisión", () => {
    const r = buildOpportunities([inp({})], 3000, 10000, 0.25);
    const d = r.decisions[0];
    expect(d.action).toBe("ESPERAR");
    expect(d.valuationLine.toLowerCase()).toContain("descriptiva");
    expect(d.missing.join(" ").toLowerCase()).toContain("valoración fundada");
  });

  it("la alerta de ciclicidad se refleja en la señal (no afirma pico)", () => {
    const r = buildOpportunities(
      [inp({ valuation: val({ earningsYield: 0.12, cyclicalAlert: true, cyclicalNote: "alerta" }) })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("ESPERAR");
    expect(r.decisions[0].missing.join(" ").toLowerCase()).toContain("ciclicidad");
  });
});

describe("brecha de datos → INVESTIGAR (no veredicto)", () => {
  it("sin valoración disponible → INVESTIGAR y lo declara brecha de datos", () => {
    const r = buildOpportunities(
      [inp({ valuation: { ...val(), available: false, unavailableReason: "Sin EPS en EDGAR" } })],
      3000, 10000, 0.25,
    );
    expect(r.decisions[0].action).toBe("INVESTIGAR");
    expect(r.decisions[0].valuationLine.toLowerCase()).toContain("brecha de datos");
  });

  it("calidad de datos baja → INVESTIGAR", () => {
    const r = buildOpportunities([inp({ valuation: val({ quality: "baja" }) })], 3000, 10000, 0.25);
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

describe("liquidez íntegra y framing de señales", () => {
  it("nunca se despliega capital: deployed 0 y liquidez completa", () => {
    const r = buildOpportunities(
      [
        inp({ ticker: "A", valuation: val({ earningsYield: 0.20 }) }),
        inp({ ticker: "B", valuation: val({ earningsYield: 0.12 }) }),
      ],
      3000, 100000, 0.25,
    );
    expect(r.deployed).toBe(0);
    expect(r.cashKept).toBe(3000);
    expect(r.decisions.every((d) => d.suggestedAmountUsd == null)).toBe(true);
  });

  it("la nota aclara que son señales, no decisiones de compra", () => {
    const r = buildOpportunities([inp({})], 3000, 10000, 0.25);
    expect(r.note.toLowerCase()).toContain("no decisiones");
    expect(r.note.toLowerCase()).toContain("no emite compra");
  });
});
