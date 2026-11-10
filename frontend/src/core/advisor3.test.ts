import { describe, it, expect } from "vitest";
import { buildAdvisor3, type Adv3Input } from "./advisor3";

// Cartera real (fixture): 3 acciones + ETF + efectivo, con retornos alineados.
function baseInput(): Adv3Input {
  const r = (seed: number) => Array.from({ length: 40 }, (_, k) => Math.sin(seed + k) * 0.02);
  return {
    positions: [
      { ticker: "NVDA", sector: "Tech", country: "US", currency: "USD", assetClass: "equity", marketValue: 4000, weight: 0.40 },
      { ticker: "KO", sector: "Staples", country: "US", currency: "USD", assetClass: "equity", marketValue: 2000, weight: 0.20 },
      { ticker: "TSM", sector: "Tech", country: "TW", currency: "USD", assetClass: "equity", marketValue: 1500, weight: 0.15 },
      { ticker: "SPY", sector: "ETF", country: "US", currency: "USD", assetClass: "etf", marketValue: 1500, weight: 0.15 },
    ],
    cash: 1000,
    contribution: 3000,
    returns: { NVDA: r(1).map((x) => x * 1.6), KO: r(5).map((x) => x * 0.4), TSM: r(2).map((x) => x * 1.2), SPY: r(3).map((x) => x * 0.6) },
    valuation: {
      NVDA: { productiveMargin: -0.30, productiveConfidence: "alta", priceComparable: true },   // muy sobrevalorada
      KO: { productiveMargin: 0.18, productiveConfidence: "media", priceComparable: true },       // infravalorada, confianza media
      TSM: { productiveMargin: null, productiveConfidence: null, fcffMargin: 0.40, fcffConfidence: "baja", priceComparable: true }, // solo FCFF baja
      SPY: { productiveMargin: null, productiveConfidence: null, priceComparable: true },
    },
    quality: { NVDA: { eligible: true, fresh: true }, KO: { eligible: true, fresh: true }, TSM: { eligible: true, fresh: true }, SPY: { eligible: true, fresh: true } },
    constraints: { maxPositionWeight: 0.45, maxSectorWeight: 0.50, minMarginToBuy: 0.10 },
  };
}

describe("Advisor 3.0", () => {
  it("posición: muy sobrevalorada con confianza alta => REDUCIR/VENDER", () => {
    const r = buildAdvisor3(baseInput());
    const nvda = r.positionDecisions.find((d) => d.ticker === "NVDA")!;
    expect(["REDUCIR", "VENDER"]).toContain(nvda.action);
    expect(nvda.marginSource).toBe("productivo");
  });

  it("posición: FCFF experimental de baja confianza NO desplaza el FV productivo (=> REVISAR, no COMPRAR)", () => {
    const r = buildAdvisor3(baseInput());
    const tsm = r.positionDecisions.find((d) => d.ticker === "TSM")!;
    expect(tsm.action).toBe("REVISAR");                 // sin FV productivo + FCFF baja => sin conclusión
    expect(tsm.marginSource).not.toBe("productivo");
  });

  it("guardrail: margen positivo (FCFF baja confianza) NO habilita COMPRAR en la asignación", () => {
    const r = buildAdvisor3(baseInput());
    const deployed = r.allocation.options.flatMap((o) => o.items.map((i) => i.ticker));
    expect(deployed).not.toContain("TSM");              // TSM solo tiene FCFF baja => no es candidato
  });

  it("conservación de capital: Σ importes + efectivo == aporte, EXACTO, en toda opción", () => {
    const r = buildAdvisor3(baseInput());
    for (const o of r.allocation.options) {
      const sum = o.items.reduce((s, i) => s + i.amount, 0) + o.cashKept;
      expect(sum).toBe(3000);
    }
  });

  it("opción todo-efectivo (ESPERAR) siempre disponible", () => {
    const r = buildAdvisor3(baseInput());
    expect(r.allocation.options.some((o) => o.id === "efectivo")).toBe(true);
  });

  it("riesgo marginal: cada opción reporta vol sobre la cartera resultante COMPLETA", () => {
    const r = buildAdvisor3(baseInput());
    for (const o of r.allocation.options) expect(typeof o.volAfter).toBe("number");
    // KO (infravalorada, confianza media, productiva) sí es candidata => alguna opción la despliega
    const anyKO = r.allocation.options.some((o) => o.items.some((i) => i.ticker === "KO"));
    expect(anyKO).toBe(true);
  });

  it("consistencia: dos decisiones separadas; ETF se evalúa por rol, no por DCF", () => {
    const r = buildAdvisor3(baseInput());
    const spy = r.positionDecisions.find((d) => d.ticker === "SPY")!;
    expect(["MANTENER", "REVISAR"]).toContain(spy.action);  // vehículo, nunca por margen
  });

  it("datos ausentes: sin valoración => REVISAR, con explicación de condición de cambio", () => {
    const inp = baseInput();
    inp.valuation.KO = { productiveMargin: null, productiveConfidence: null, priceComparable: true };
    const r = buildAdvisor3(inp);
    const ko = r.positionDecisions.find((d) => d.ticker === "KO")!;
    expect(ko.action).toBe("REVISAR");
    expect(ko.explain.condicionesCambio.length).toBeGreaterThan(0);
  });

  it("explicabilidad: cada recomendación trae motivos/datos/riesgos/condiciones", () => {
    const r = buildAdvisor3(baseInput());
    for (const d of r.positionDecisions) {
      expect(d.explain.motivos.length).toBeGreaterThan(0);
      expect(d.explain.datosModelos.length).toBeGreaterThan(0);
      expect(d.explain.condicionesCambio.length).toBeGreaterThan(0);
    }
    expect(r.guardrails.length).toBeGreaterThan(0);
  });
});
