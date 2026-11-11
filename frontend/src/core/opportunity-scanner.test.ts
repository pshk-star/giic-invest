import { describe, it, expect } from "vitest";
import { buildScanner, type ScanInput } from "./opportunity-scanner";
import { buildAdvisor3, type Adv3Input } from "./advisor3";

const DATES = Array.from({ length: 30 }, (_, k) => `2026-01-${String(k + 1).padStart(2, "0")}`);
const series = (base: number, amp: number, phase: number) =>
  DATES.map((d, k) => ({ as_of: d, close: base * (1 + amp * Math.sin(phase + k * 0.5)) }));

// Cartera concentrada (NVDA Tech > 50%) + ETF + efectivo. Universo con nombres dentro y fuera.
function baseInput(): ScanInput {
  return {
    candidates: [
      { ticker: "NVDA", name: "NVIDIA", sector: "Tech", country: "US", currency: "USD", assetClass: "equity", kind: "empresa", inPortfolio: true, composite: 0.8 },
      { ticker: "KO", name: "Coca-Cola", sector: "Staples", country: "US", currency: "USD", assetClass: "equity", kind: "empresa", inPortfolio: true, composite: 0.5 },
      { ticker: "SPY", name: "S&P 500 ETF", sector: "ETF", country: "US", currency: "USD", assetClass: "etf", kind: "etf", inPortfolio: true, composite: null },
      { ticker: "AAPL", name: "Apple", sector: "Tech", country: "US", currency: "USD", assetClass: "equity", kind: "empresa", inPortfolio: false, composite: 0.7 },
      { ticker: "JPM", name: "JPMorgan", sector: "Financials", country: "US", currency: "USD", assetClass: "equity", kind: "banco", inPortfolio: false, composite: 0.6 },
      { ticker: "XYZ", name: "Solo FCFF", sector: "Industrials", country: "US", currency: "USD", assetClass: "equity", kind: "empresa", inPortfolio: false, composite: 0.4 },
      { ticker: "VWO", name: "EM ETF", sector: "EmergingMkts", country: "US", currency: "USD", assetClass: "etf", kind: "etf", inPortfolio: false, composite: null },
      { ticker: "NODATA", name: "Sin datos", sector: "Unknown", country: "US", currency: "USD", assetClass: "equity", kind: "empresa", inPortfolio: false, composite: null },
    ],
    valuation: {
      NVDA: { productiveMargin: -0.30, productiveConfidence: "media", priceComparable: true },        // cara
      KO: { productiveMargin: 0.15, productiveConfidence: "media", priceComparable: true },            // candidata valor
      SPY: { productiveMargin: null, productiveConfidence: null, priceComparable: true },              // ETF, sin DCF
      AAPL: { productiveMargin: 0.20, productiveConfidence: "media", priceComparable: true },          // infravalorada, fuera de cartera
      JPM: { productiveMargin: null, productiveConfidence: null, priceComparable: true },              // banco sin FV productivo
      XYZ: { productiveMargin: null, productiveConfidence: null, fcffMargin: 0.30, fcffConfidence: "baja", priceComparable: true }, // solo FCFF baja
      VWO: { productiveMargin: null, productiveConfidence: null, priceComparable: true },              // ETF diversificador
    },
    fundamentals: {
      AAPL: { roic: 0.30, revGrowth: 0.08, netMargin: 0.25 },
      KO: { roic: 0.18, revGrowth: 0.04, netMargin: 0.22 },
      NVDA: { roic: 0.40, revGrowth: 0.50, netMargin: 0.30 },
    },
    portfolio: {
      positions: [
        { ticker: "NVDA", sector: "Tech", country: "US", currency: "USD", assetClass: "equity", marketValue: 6000, weight: 0.545 },
        { ticker: "KO", sector: "Staples", country: "US", currency: "USD", assetClass: "equity", marketValue: 2000, weight: 0.182 },
        { ticker: "SPY", sector: "ETF", country: "US", currency: "USD", assetClass: "etf", marketValue: 2000, weight: 0.182 },
      ],
      cash: 1000,
    },
    priceHistory: {
      NVDA: series(100, 0.30, 1), KO: series(60, 0.08, 2), SPY: series(400, 0.12, 3),
      AAPL: series(180, 0.20, 4), JPM: series(150, 0.15, 5), XYZ: series(40, 0.25, 6), VWO: series(45, 0.10, 7),
    },
    etfLookthrough: { SPY: { NVDA: 0.07, AAPL: 0.06 } },   // exposición ya presente vía SPY
    contributions: [1000, 3000],
    constraints: { maxPositionWeight: 0.45, maxSectorWeight: 0.50, minMarginToBuy: 0.10 },
  };
}

describe("P2.2 Opportunity Scanner", () => {
  it("universo completo: evalúa dentro, fuera y ETF; excluye solo lo que no tiene datos", () => {
    const r = buildScanner(baseInput());
    expect(r.universeSize).toBe(8);
    expect(r.evaluated).toBe(7);                                   // NODATA fuera
    expect(r.excluded.map((e) => e.ticker)).toContain("NODATA");
  });

  it("empresas fuera de cartera: se simulan con peso inicial 0 y la cartera crece por el aporte", () => {
    const r = buildScanner(baseInput());
    const aapl = r.entries.find((e) => e.ticker === "AAPL")!;
    expect(aapl.inPortfolio).toBe(false);
    expect(aapl.sims[0].weightBefore).toBe(0);
    expect(aapl.sims[0].weightAfter).toBeGreaterThan(0);
  });

  it("conservación de capital: totalAfter == portfolioValue + aporte, y cashIfFunded + aporte == efectivo (exacto)", () => {
    const r = buildScanner(baseInput());
    for (const e of r.entries) for (const s of e.sims) {
      expect(s.totalAfter).toBe(r.portfolioValue + s.amount);
      expect(s.cashIfFunded + s.amount).toBe(r.cash);
    }
  });

  it("riesgo marginal: contribución del candidato calculada sobre la cartera RESULTANTE", () => {
    const r = buildScanner(baseInput());
    const aapl = r.entries.find((e) => e.ticker === "AAPL")!;
    expect(typeof aapl.sims[1].marginalRiskContribPct).toBe("number");
    expect(aapl.sims[1].volAfter).toBeGreaterThan(0);
    // exposición duplicada vía SPY (0.06 * peso de SPY) se reporta
    expect(aapl.sims[0].duplicatedExposure).toBeGreaterThan(0);
  });

  it("ranking fundamental: solo empresas con FV productivo, ordenadas desc; ETF excluidos", () => {
    const r = buildScanner(baseInput());
    const fund = r.rankings.find((x) => x.id === "fundamental")!;
    const tk = fund.entries.map((e) => e.ticker);
    expect(tk).toContain("AAPL");
    expect(tk).not.toContain("SPY");                               // ETF no se valora por DCF
    expect(tk).not.toContain("JPM");                               // sin FV productivo
    // orden descendente por score
    const scores = fund.entries.map((e) => e.fundamentalScore!);
    expect([...scores].sort((a, b) => b - a)).toEqual(scores);
    expect(tk[0]).toBe("AAPL");                                    // mejor margen+calidad arriba
  });

  it("ranking diversificación: ordenado por reducción de HHI; expone Δvol (menor vol no es mejor por defecto)", () => {
    const r = buildScanner(baseInput());
    const div = r.rankings.find((x) => x.id === "diversificacion")!;
    expect(div.entries.length).toBeGreaterThan(0);
    for (const e of div.entries) expect(e.diversificationScore!).toBeGreaterThan(0);
    const sc = div.entries.map((e) => e.diversificationScore!);
    expect([...sc].sort((a, b) => b - a)).toEqual(sc);
    expect(div.note).toMatch(/menor vol/i);
  });

  it("accionable: AAPL/KO por VALOR; VWO por DIVERSIFICACIÓN (cartera concentrada)", () => {
    const r = buildScanner(baseInput());
    expect(r.hasConcentrationProblem).toBe(true);
    const acc = r.rankings.find((x) => x.id === "accionable")!;
    const byTicker = Object.fromEntries(acc.entries.map((e) => [e.ticker, e.actionableBasis]));
    expect(byTicker["AAPL"]).toBe("valor");
    expect(byTicker["KO"]).toBe("valor");
    expect(byTicker["VWO"]).toBe("diversificador");
    // valor antes que diversificador en el orden
    const idxValor = acc.entries.findIndex((e) => e.actionableBasis === "valor");
    const idxDiv = acc.entries.findIndex((e) => e.actionableBasis === "diversificador");
    expect(idxValor).toBeLessThan(idxDiv);
  });

  it("datos insuficientes: banco sin FV productivo no es fundamental ni accionable, confianza degradada", () => {
    const r = buildScanner(baseInput());
    const jpm = r.entries.find((e) => e.ticker === "JPM")!;
    expect(jpm.fundamentalScore).toBeNull();
    expect(jpm.actionable).toBe(false);
    expect(jpm.missing.join(" ")).toMatch(/FV productivo/i);
  });

  it("sin compra por margen positivo solo: FCFF +30% de baja confianza NO es accionable", () => {
    const r = buildScanner(baseInput());
    const xyz = r.entries.find((e) => e.ticker === "XYZ")!;
    expect(xyz.actionable).toBe(false);
    expect(xyz.marginSource).not.toBe("productivo");
    // tampoco aparece en el ranking accionable
    const acc = r.rankings.find((x) => x.id === "accionable")!;
    expect(acc.entries.map((e) => e.ticker)).not.toContain("XYZ");
  });

  it("ranking estable y reproducible: dos corridas producen el mismo orden", () => {
    const a = buildScanner(baseInput(), "2026-11-10");
    const b = buildScanner(baseInput(), "2026-11-10");
    for (const id of ["fundamental", "diversificacion", "accionable"] as const) {
      const ra = a.rankings.find((x) => x.id === id)!.entries.map((e) => e.ticker);
      const rb = b.rankings.find((x) => x.id === id)!.entries.map((e) => e.ticker);
      expect(ra).toEqual(rb);
    }
  });

  it("ETF y sectores especiales: NVDA cara sigue en fundamental (score negativo), no accionable", () => {
    const r = buildScanner(baseInput());
    const nvda = r.entries.find((e) => e.ticker === "NVDA")!;
    expect(nvda.fundamentalScore!).toBeLessThan(0);                // cara => score negativo, no se oculta
    expect(nvda.actionable).toBe(false);
    const acc = r.rankings.find((x) => x.id === "accionable")!;
    expect(acc.entries.map((e) => e.ticker)).not.toContain("NVDA");
  });

  it("control: guardrails y procedencia presentes; no inventa accionables sin datos", () => {
    const r = buildScanner(baseInput());
    expect(r.guardrails.length).toBeGreaterThan(0);
    expect(r.dataProvenance.length).toBeGreaterThan(0);
    const acc = r.rankings.find((x) => x.id === "accionable")!;
    expect(acc.entries.map((e) => e.ticker)).not.toContain("NODATA");
  });

  // ---------- P2.3 — Cobertura y validación end-to-end ----------

  it("P2.3 cobertura: cuenta universo, evaluados, excluidos y disponibilidad de datos", () => {
    const r = buildScanner(baseInput());
    expect(r.coverage.total).toBe(8);
    expect(r.coverage.evaluated).toBe(7);
    expect(r.coverage.excluded).toBe(1);
    expect(r.coverage.withProductiveFv).toBe(3);   // NVDA, KO, AAPL
    expect(r.coverage.withFcff).toBe(1);           // XYZ
    expect(r.coverage.eligibleCompanies).toBe(6);  // NVDA,KO,AAPL,JPM,XYZ,NODATA (empresa/banco)
  });

  it("P2.3 clasificación de 4 vías: suma igual al universo total", () => {
    const r = buildScanner(baseInput());
    const c = r.coverage.classification;
    expect(c.no_evaluable + c.evaluable_no_atractivo + c.atractivo_no_accionable + c.accionable).toBe(r.coverage.total);
    expect(c.no_evaluable).toBeGreaterThanOrEqual(1);   // NODATA
    expect(c.accionable).toBeGreaterThanOrEqual(1);      // AAPL/KO
  });

  it("P2.3 bloqueo por DCF productivo: FCFF atractivo + sin FV productivo => atractivo_no_accionable", () => {
    const inp = baseInput();
    inp.valuation.JPM = { productiveMargin: null, productiveConfidence: null, fcffMargin: 0.25, fcffConfidence: "media", priceComparable: true };
    const r = buildScanner(inp);
    const jpm = r.entries.find((e) => e.ticker === "JPM")!;
    expect(jpm.blockedByProductiveVeto).toBe(true);
    expect(jpm.classification).toBe("atractivo_no_accionable");
    expect(jpm.actionable).toBe(false);                  // la regla NO se cambia en P2.3
    expect(r.coverage.blockedByProductiveVeto.tickers).toContain("JPM");
  });

  it("P2.3 FCFF de baja confianza NO cuenta como bloqueo (no es atractivo de verdad)", () => {
    const r = buildScanner(baseInput());
    const xyz = r.entries.find((e) => e.ticker === "XYZ")!;   // fcff +30% pero confianza baja
    expect(xyz.blockedByProductiveVeto).toBe(false);
  });

  it("P2.3 consistencia Scanner↔Advisor 3.0: un nombre accionable por VALOR es candidato de compra en Advisor 3.0", () => {
    const inp = baseInput();
    const r = buildScanner(inp);
    const ko = r.entries.find((e) => e.ticker === "KO")!;
    expect(ko.actionable && ko.actionableBasis === "valor").toBe(true);
    // mismo criterio (passesValueGate) en Advisor 3.0: KO debe aparecer como candidato desplegable
    const toRet = (bars: { close: number }[]) => bars.slice(1).map((b, i) => bars[i].close > 0 ? b.close / bars[i].close - 1 : 0);
    const advReturns = Object.fromEntries(inp.portfolio.positions.map((p) => [p.ticker, toRet(inp.priceHistory[p.ticker] ?? [])]));
    const adv: Adv3Input = {
      positions: inp.portfolio.positions,
      cash: 0, contribution: 3000, returns: advReturns,
      valuation: inp.valuation,
      quality: Object.fromEntries(inp.portfolio.positions.map((p) => [p.ticker, { eligible: true, fresh: true }])),
      constraints: inp.constraints,
    };
    const a3 = buildAdvisor3(adv);
    const deployedTickers = new Set(a3.allocation.options.flatMap((o) => o.items.map((i) => i.ticker)));
    expect(deployedTickers.has("KO")).toBe(true);
  });

  it("P2.3 rendimiento: evaluar el universo es O(n) y no lanza con universo mayor", () => {
    const inp = baseInput();
    // duplica el universo con nombres sintéticos fuera de cartera, con y sin datos
    for (let i = 0; i < 40; i++) {
      const t = `SYN${i}`;
      inp.candidates.push({ ticker: t, name: t, sector: i % 2 ? "Tech" : "Health", country: "US", currency: "USD", assetClass: "equity", kind: "empresa", inPortfolio: false, composite: null });
      inp.priceHistory[t] = DATES.map((d, k) => ({ as_of: d, close: 50 * (1 + 0.1 * Math.sin(i + k * 0.4)) }));
      if (i % 3 === 0) inp.valuation[t] = { productiveMargin: 0.12, productiveConfidence: "media", priceComparable: true };
    }
    const t0 = Date.now();
    const r = buildScanner(inp);
    expect(Date.now() - t0).toBeLessThan(2000);
    expect(r.coverage.total).toBe(48);
    expect(r.coverage.evaluated).toBeGreaterThanOrEqual(47);
  });
});
