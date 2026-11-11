import { describe, it, expect } from "vitest";
import { buildScanner, type ScanInput } from "./opportunity-scanner";
import { buildAllocationPlan } from "./allocation-planner";

const DATES = Array.from({ length: 30 }, (_, k) => `2026-01-${String(k + 1).padStart(2, "0")}`);
const series = (base: number, amp: number, phase: number) =>
  DATES.map((d, k) => ({ as_of: d, close: base * (1 + amp * Math.sin(phase + k * 0.5)) }));

function baseInput(): ScanInput {
  const emp = (ticker: string, sector: string, inPortfolio = false) =>
    ({ ticker, name: ticker, sector, country: "US", currency: "USD", assetClass: "equity", kind: "empresa" as const, inPortfolio });
  return {
    candidates: [
      emp("NVDA", "Tech", true), { ticker: "SPY", name: "SPY", sector: "ETF", country: "US", currency: "USD", assetClass: "etf", kind: "etf", inPortfolio: true },
      emp("AAA", "Health"), emp("BBB", "Energy"), emp("CCC", "Retail"), emp("DDD", "Health"),
      emp("LOWC", "Utilities"), emp("CTXT", "Industrials"),
    ],
    valuation: {
      NVDA: { productiveMargin: -0.30, productiveConfidence: "media", priceComparable: true },
      SPY: { productiveMargin: null, productiveConfidence: null, priceComparable: true },
      AAA: { productiveMargin: 0.20, productiveConfidence: "media", priceComparable: true },
      BBB: { productiveMargin: 0.25, productiveConfidence: "media", priceComparable: true },
      CCC: { productiveMargin: 0.15, productiveConfidence: "media", priceComparable: true },
      DDD: { productiveMargin: 0.12, productiveConfidence: "media", priceComparable: true },
      LOWC: { productiveMargin: 0.30, productiveConfidence: null, fcffMargin: 0.30, fcffConfidence: "baja", priceComparable: true }, // baja confianza
      CTXT: { productiveMargin: null, productiveConfidence: null, fcffMargin: 0.40, fcffConfidence: "media", priceComparable: true }, // atractivo por FCFF pero NO accionable (fallback off)
    },
    fundamentals: {},
    portfolio: {
      positions: [
        { ticker: "NVDA", sector: "Tech", country: "US", currency: "USD", assetClass: "equity", marketValue: 4000, weight: 0.4 },
        { ticker: "SPY", sector: "ETF", country: "US", currency: "USD", assetClass: "etf", marketValue: 2000, weight: 0.2 },
      ],
      cash: 0,
    },
    priceHistory: {
      NVDA: series(100, 0.3, 1), SPY: series(400, 0.12, 2), AAA: series(80, 0.1, 3), BBB: series(120, 0.18, 4),
      CCC: series(60, 0.14, 5), DDD: series(90, 0.11, 6), LOWC: series(50, 0.07, 7), CTXT: series(70, 0.2, 8),
    },
    contributions: [1000, 3000],
    constraints: { maxPositionWeight: 0.45, maxSectorWeight: 0.50, minMarginToBuy: 0.10 },
  };
}

function plan(inp: ScanInput, contribution = 3000) {
  const report = buildScanner(inp);
  return buildAllocationPlan(inp, report, contribution);
}

describe("P2.5 asignación multiposición", () => {
  it("conservación exacta de capital en TODA propuesta (Σ importes + efectivo = aporte)", () => {
    const p = plan(baseInput());
    for (const pr of p.proposals) {
      const dep = pr.legs.reduce((s, l) => s + l.amount, 0);
      expect(dep + pr.cashKept).toBe(p.contribution);
      expect(pr.deployed).toBe(dep);
    }
  });

  it("inversión completa distribuye en VARIAS posiciones (multiposición)", () => {
    const completa = plan(baseInput()).proposals.find((x) => x.id === "completa")!;
    expect(completa.legs.length).toBeGreaterThanOrEqual(2);
    const sectores = new Set(completa.legs.map((l) => l.sector));
    expect(sectores.size).toBeGreaterThanOrEqual(2);   // diversifica entre sectores
  });

  it("respeta tope por empresa (peso resultante ≤ maxPositionWeight)", () => {
    const p = plan(baseInput());
    for (const pr of p.proposals) for (const l of pr.legs) {
      expect(l.weightAfter).toBeLessThanOrEqual(0.45 + 1e-6);
    }
  });

  it("valoración experimental (FCFF fallback) ⇒ asignación limitada (≤15% del aporte)", () => {
    const inp = baseInput();
    inp.fcffFallback = true;   // habilita fallback; EXPF se vuelve accionable experimental
    inp.candidates.push({ ticker: "EXPF", name: "EXPF", sector: "Materials", country: "US", currency: "USD", assetClass: "equity", kind: "empresa", inPortfolio: false });
    inp.valuation.EXPF = { productiveMargin: null, productiveConfidence: null, fcffMargin: 0.30, fcffConfidence: "media", priceComparable: true };
    inp.priceHistory.EXPF = series(55, 0.09, 9);
    const completa = plan(inp).proposals.find((x) => x.id === "completa")!;
    const exp = completa.legs.find((l) => l.ticker === "EXPF");
    expect(exp).toBeTruthy();                                  // es accionable por fallback
    expect(exp!.amount).toBeLessThanOrEqual(0.15 * 3000 + 1);  // pero asignación limitada
  });

  it("margen positivo NO es compra automática: un nombre no accionable (FCFF, fallback off) no entra", () => {
    const p = plan(baseInput());
    const tickers = new Set(p.proposals.flatMap((pr) => pr.legs.map((l) => l.ticker)));
    expect(tickers.has("CTXT")).toBe(false);
    expect(p.discarded.map((d) => d.ticker)).toContain("CTXT");
  });

  it("compara completa/parcial/efectivo; parcial no despliega más que completa; efectivo es 0", () => {
    const p = plan(baseInput());
    const by = Object.fromEntries(p.proposals.map((x) => [x.id, x]));
    expect(by["efectivo"].deployed).toBe(0);
    expect(by["parcial"].deployed).toBeLessThanOrEqual(by["completa"].deployed);
    expect(["completa", "parcial", "efectivo"]).toContain(p.chosen);
  });

  it("con oportunidades sólidas elige desplegar (no siempre efectivo)", () => {
    const p = plan(baseInput());
    expect(p.chosen).not.toBe("efectivo");
  });

  it("sin oportunidades accionables ⇒ ESPERAR (efectivo)", () => {
    const inp = baseInput();
    // quita todos los márgenes productivos: nada accionable por valor
    for (const t of ["AAA", "BBB", "CCC", "DDD", "LOWC"]) inp.valuation[t] = { productiveMargin: -0.20, productiveConfidence: "media", priceComparable: true };
    const p = plan(inp);
    expect(p.chosen).toBe("efectivo");
  });

  it("cada leg explica por qué (margen/confianza) y reporta riesgo marginal y peso resultante", () => {
    const completa = plan(baseInput()).proposals.find((x) => x.id === "completa")!;
    for (const l of completa.legs) {
      expect(l.reason.length).toBeGreaterThan(0);
      expect(l.weightAfter).toBeGreaterThan(0);
    }
  });

  it("explica alternativas descartadas y trae guardrails", () => {
    const p = plan(baseInput());
    expect(p.discarded.length).toBeGreaterThan(0);
    expect(p.guardrails.length).toBeGreaterThan(0);
  });
});
