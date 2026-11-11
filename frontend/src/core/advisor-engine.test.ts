import { describe, it, expect } from "vitest";
import { buildUnifiedAdvisor } from "./advisor-engine";
import { deriveConstraints, investableAmount, missingEssentials, profileFromSettings, type Profile } from "./advisor-profile";
import type { ScanInput } from "./opportunity-scanner";

const DATES = Array.from({ length: 30 }, (_, k) => `2026-01-${String(k + 1).padStart(2, "0")}`);
const series = (base: number, amp: number, phase: number) => DATES.map((d, k) => ({ as_of: d, close: base * (1 + amp * Math.sin(phase + k * 0.5)) }));

function scanInput(): ScanInput {
  const emp = (ticker: string, sector: string, inPortfolio = false) =>
    ({ ticker, name: ticker, sector, country: "US", currency: "USD", assetClass: "equity", kind: "empresa" as const, inPortfolio });
  return {
    candidates: [
      emp("NVDA", "Tech", true), emp("KO", "Staples", true),
      { ticker: "SPY", name: "SPY", sector: "ETF", country: "US", currency: "USD", assetClass: "etf", kind: "etf", inPortfolio: true },
      emp("AAA", "Health"), emp("EXP", "Energy"), emp("POOR", "Retail"), emp("INSUF", "Materials"),
    ],
    valuation: {
      NVDA: { productiveMargin: -0.30, productiveConfidence: "media", priceComparable: true },
      KO: { productiveMargin: 0.15, productiveConfidence: "media", priceComparable: true },
      SPY: { productiveMargin: null, productiveConfidence: null, priceComparable: true },
      AAA: { productiveMargin: 0.20, productiveConfidence: "media", priceComparable: true },
      EXP: { productiveMargin: null, productiveConfidence: null, fcffMargin: 0.30, fcffConfidence: "media", priceComparable: true },
      POOR: { productiveMargin: 0.05, productiveConfidence: "media", priceComparable: true },
      INSUF: { productiveMargin: null, productiveConfidence: null, priceComparable: true },
    },
    fundamentals: {},
    portfolio: {
      positions: [
        { ticker: "NVDA", sector: "Tech", country: "US", currency: "USD", assetClass: "equity", marketValue: 4000, weight: 0.533 },
        { ticker: "KO", sector: "Staples", country: "US", currency: "USD", assetClass: "equity", marketValue: 1500, weight: 0.20 },
        { ticker: "SPY", sector: "ETF", country: "US", currency: "USD", assetClass: "etf", marketValue: 2000, weight: 0.267 },
      ],
      cash: 0,
    },
    priceHistory: {
      NVDA: series(100, 0.3, 1), KO: series(60, 0.08, 2), SPY: series(400, 0.12, 3),
      AAA: series(80, 0.1, 4), EXP: series(50, 0.09, 5), POOR: series(70, 0.07, 6), INSUF: series(55, 0.11, 7),
    },
    contributions: [3000],
    constraints: { maxPositionWeight: 0.45, maxSectorWeight: 0.50, minMarginToBuy: 0.10 },
    fcffFallback: true,
  };
}
const PROFILE: Profile = { baseCurrency: "USD", capitalAvailable: 5000, monthlyContribution: 3000, riskTolerance: "moderado", horizonYears: 10, maxWeightPerAsset: null, maxWeightPerSector: null, minCash: 1000 };

describe("Etapa A — perfil", () => {
  it("deriva constraints por tolerancia cuando el perfil no fija topes", () => {
    expect(deriveConstraints({ ...PROFILE, riskTolerance: "conservador" }).maxPositionWeight).toBe(0.20);
    expect(deriveConstraints({ ...PROFILE, riskTolerance: "agresivo" }).maxPositionWeight).toBe(0.45);
    const c = deriveConstraints({ ...PROFILE, maxWeightPerAsset: 0.33 });
    expect(c.maxPositionWeight).toBe(0.33);          // tope explícito del perfil manda
    expect(c.posSource).toBe("perfil");
  });
  it("capital a invertir: aporte mensual o (disponible - efectivo mínimo)", () => {
    expect(investableAmount(PROFILE)).toBe(3000);
    expect(investableAmount({ ...PROFILE, monthlyContribution: null })).toBe(4000);   // 5000-1000
  });
  it("pide datos esenciales faltantes (no inventa)", () => {
    expect(missingEssentials(null)).toContain("moneda base");
    expect(missingEssentials({ ...PROFILE, riskTolerance: null })).toEqual(["tolerancia al riesgo"]);
    expect(missingEssentials(PROFILE)).toEqual([]);
  });
  it("profileFromSettings mapea la fila de settings", () => {
    const p = profileFromSettings({ base_currency: "USD", capital_available: 10000, risk_tolerance: "agresivo" });
    expect(p.baseCurrency).toBe("USD"); expect(p.capitalAvailable).toBe(10000); expect(p.riskTolerance).toBe("agresivo");
  });
});

describe("Etapa A — orquestador (una sola recomendación)", () => {
  it("una acción por posición de cartera", () => {
    const r = buildUnifiedAdvisor({ profile: PROFILE, scanInput: scanInput() });
    expect(r.positions.map((p) => p.ticker).sort()).toEqual(["KO", "NVDA", "SPY"]);
    for (const p of r.positions) expect(["MANTENER", "ACUMULAR", "REDUCIR", "VENDER", "REVISAR"]).toContain(p.action);
  });

  it("KO infravalorada con holgura ⇒ ACUMULAR; NVDA sobrevalorada ⇒ REDUCIR", () => {
    const r = buildUnifiedAdvisor({ profile: PROFILE, scanInput: scanInput() });
    expect(r.positions.find((p) => p.ticker === "KO")!.action).toBe("ACUMULAR");
    expect(r.positions.find((p) => p.ticker === "NVDA")!.action).toBe("REDUCIR");
  });

  it("clasifica oportunidades: atractiva / pendiente_analisis / poco_atractiva / evidencia_insuficiente", () => {
    const r = buildUnifiedAdvisor({ profile: PROFILE, scanInput: scanInput() });
    const by = Object.fromEntries(r.opportunities.map((o) => [o.ticker, o.class]));
    expect(by["AAA"]).toBe("atractiva");               // FV productivo + margen
    expect(by["EXP"]).toBe("pendiente_analisis");      // FCFF experimental (no se trata como confiable)
    expect(by["POOR"]).toBe("poco_atractiva");         // valorada sin margen
    expect(by["INSUF"]).toBe("evidencia_insuficiente");// sin valoración
  });

  it("propone asignación concreta de dinero nuevo y conserva el resto; prioridades de investigación", () => {
    const r = buildUnifiedAdvisor({ profile: PROFILE, scanInput: scanInput() });
    expect(r.newMoney.contribution).toBe(3000);
    const sum = r.newMoney.legs.reduce((s, l) => s + l.amount, 0) + r.newMoney.cashKept;
    expect(sum).toBe(3000);                            // conservación exacta
    expect(r.researchPriorities.map((x) => x.ticker)).toContain("EXP");  // experimental atractivo => profundizar
    expect(r.executiveSummary.length).toBeGreaterThan(0);
    expect(["desplegar", "parcial", "esperar"]).toContain(r.posture);
  });

  it("coherencia: una posición accionable por VALOR no aparece simultáneamente como 'no tocar' sin explicar", () => {
    const r = buildUnifiedAdvisor({ profile: PROFILE, scanInput: scanInput() });
    const ko = r.positions.find((p) => p.ticker === "KO")!;
    expect(ko.action).toBe("ACUMULAR");                // misma política: barata+holgura => acumular, no contradicción
    expect(ko.why.length).toBeGreaterThan(0);
  });

  it("constraints provienen del perfil/tolerancia (sin parámetros manuales), con procedencia", () => {
    const r = buildUnifiedAdvisor({ profile: { ...PROFILE, riskTolerance: "conservador" }, scanInput: scanInput() });
    expect(r.constraintsUsed.maxPositionWeight).toBe(0.20);
    expect(r.constraintsUsed.sources.empresa).toMatch(/tolerancia/);
  });

  it("sin oportunidades accionables ⇒ recomienda efectivo (esperar), no fuerza compras", () => {
    const inp = scanInput();
    inp.fcffFallback = false;                           // sin fallback, los experimentales no son accionables
    for (const t of ["AAA", "KO"]) inp.valuation[t] = { productiveMargin: -0.20, productiveConfidence: "media", priceComparable: true };
    const r = buildUnifiedAdvisor({ profile: PROFILE, scanInput: inp });
    expect(r.posture).toBe("esperar");
    expect(r.newMoney.chosen).toBe("efectivo");
  });
});
