// Pruebas de PARIDAD con el núcleo Python (backend/tests/test_portfolio.py).
// Se ejecutan en CI con vitest (`npm test`). No se pueden correr en el sandbox de
// construcción (sin node_modules), pero sí en GitHub Actions / local.
import { describe, expect, it } from "vitest";
import {
  concentrationReport,
  distribution,
  effectiveHoldings,
  herfindahl,
  lookThrough,
  valuation,
  type Position,
  type PriceInfo,
} from "./analytics";

const inst = (
  ticker: string,
  asset_class: string,
  sector: string,
  quantity: number,
  avg_cost: number,
  currency = "USD"
): Position => ({ ticker, name: ticker, asset_class, sector, country: "US", currency, quantity, avg_cost });

const px = (close: number): PriceInfo => ({ close, as_of: "2026-11-05", currency: "USD" });

describe("valuation", () => {
  it("P&L y pesos", () => {
    const v = valuation(
      [inst("NVDA", "equity", "Tech", 10, 100), inst("KO", "equity", "Staples", 20, 50)],
      { NVDA: px(120), KO: px(60) }
    );
    expect(v.total_market_value).toBe(10 * 120 + 20 * 60);
    const w = v.positions.reduce((s, r) => s + (r.weight ?? 0), 0);
    expect(Math.abs(w - 1)).toBeLessThan(1e-9);
  });

  it("precio faltante se reporta, no se inventa", () => {
    const v = valuation([inst("NVDA", "equity", "T", 10, 100), inst("XYZ", "equity", "T", 5, 10)], { NVDA: px(120) });
    expect(v.missing_prices).toContain("XYZ");
  });

  it("FX: sin tasa no asume 1:1", () => {
    const v = valuation([inst("WALMEX", "equity", "T", 100, 70, "MXN")], { WALMEX: px(70) }, {});
    expect(v.missing_prices).toContain("WALMEX");
    const v2 = valuation([inst("WALMEX", "equity", "T", 100, 70, "MXN")], { WALMEX: px(70) }, { MXN: 1 / 18.5 });
    expect(Math.abs((v2.positions[0].market_value ?? 0) - (100 * 70) / 18.5)).toBeLessThan(1e-6);
  });
});

describe("look-through", () => {
  it("combina directa + ETF (NVDA en QQQ y SMH)", () => {
    const positions = [
      inst("NVDA", "equity", "Semis", 10, 100),
      inst("QQQ", "etf", "ETF", 10, 400),
      inst("SMH", "etf", "ETF", 10, 200),
    ];
    const prices = { NVDA: px(180), QQQ: px(480), SMH: px(260) };
    const holdings = {
      QQQ: [{ ticker: "NVDA", weight: 0.085 }, { ticker: "MSFT", weight: 0.08 }],
      SMH: [{ ticker: "NVDA", weight: 0.2 }, { ticker: "TSM", weight: 0.12 }],
    };
    const lt = lookThrough(positions, prices, holdings);
    const nvda = lt.effective_exposure.find((e) => e.ticker === "NVDA")!;
    const expected = 1800 + 4800 * 0.085 + 2600 * 0.2;
    expect(Math.abs(nvda.effective_value - expected)).toBeLessThan(1e-6);
  });

  it("cobertura parcial => :resto", () => {
    const lt = lookThrough([inst("QQQ", "etf", "ETF", 10, 100)], { QQQ: px(100) }, { QQQ: [{ ticker: "NVDA", weight: 0.3 }] });
    const resto = lt.effective_exposure.find((e) => e.ticker === "QQQ:resto")!;
    expect(Math.abs(resto.effective_value - 1000 * 0.7)).toBeLessThan(1e-6);
    expect(lt.coverage_warnings[0].etf).toBe("QQQ");
  });
});

describe("concentración y distribución", () => {
  it("HHI y posiciones efectivas", () => {
    expect(Math.abs(herfindahl([0.25, 0.25, 0.25, 0.25]) - 0.25)).toBeLessThan(1e-9);
    expect(Math.abs(effectiveHoldings([0.25, 0.25, 0.25, 0.25]) - 4)).toBeLessThan(1e-9);
  });

  it("marca incumplimientos de límite", () => {
    const rep = concentrationReport(
      { effective_exposure: [
        { ticker: "NVDA", effective_value: 40, effective_weight: 0.4 },
        { ticker: "KO", effective_value: 60, effective_weight: 0.6 },
      ] },
      0.25
    );
    expect(rep.breaches.map((b) => b.ticker).sort()).toEqual(["KO", "NVDA"]);
  });

  it("distribución por sector", () => {
    const v = valuation([inst("NVDA", "equity", "Semis", 10, 100), inst("KO", "equity", "Staples", 10, 100)], { NVDA: px(100), KO: px(100) });
    const d = distribution(v, "sector");
    expect(Math.abs(d.Semis - 0.5)).toBeLessThan(1e-9);
  });
});
