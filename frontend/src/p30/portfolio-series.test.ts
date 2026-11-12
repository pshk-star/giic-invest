import { describe, it, expect } from "vitest";
import { portfolioSeries, periodReturn, sparkPoints, type Bar } from "./portfolio-series";

const bars = (vals: [string, number][]): Bar[] => vals.map(([as_of, close]) => ({ as_of, close }));

describe("P3.0 serie de cartera (pura)", () => {
  const history: Record<string, Bar[]> = {
    AAA: bars([["2026-01-01", 10], ["2026-02-01", 12], ["2026-03-01", 11], ["2026-04-01", 14]]),
    BBB: bars([["2026-01-01", 100], ["2026-02-01", 100], ["2026-03-01", 110], ["2026-04-01", 120]]),
  };
  const holdings = [{ ticker: "AAA", qty: 10 }, { ticker: "BBB", qty: 1 }];

  it("valor = Σ qty × precio histórico, alineado por fecha", () => {
    const s = portfolioSeries(holdings, history);
    expect(s.length).toBe(4);
    expect(s[0].value).toBe(200);   // 10*10 + 1*100
    expect(s[3].value).toBe(260);   // 10*14 + 1*120
  });

  it("sin look-ahead: usa el último precio con as_of ≤ fecha", () => {
    const h2: Record<string, Bar[]> = { AAA: bars([["2026-01-01", 10], ["2026-03-01", 20]]) };
    const s = portfolioSeries([{ ticker: "AAA", qty: 2 }], h2);
    // en 2026-01-01 => 20; en 2026-03-01 => 40 (no anticipa el precio de marzo en enero)
    expect(s[0].value).toBe(20);
    expect(s[s.length - 1].value).toBe(40);
  });

  it("omite tickers sin precios (no inventa)", () => {
    const s = portfolioSeries([{ ticker: "AAA", qty: 10 }, { ticker: "ZZZ", qty: 5 }], history);
    expect(s[0].value).toBe(100);   // solo AAA
  });

  it("retorno del periodo sobre la serie", () => {
    const s = portfolioSeries(holdings, history);
    const r = periodReturn(s, 3);   // ~3 meses: de 200 a 260
    expect(r).toBeCloseTo(260 / 200 - 1, 6);
  });

  it("retorno null si la serie no cubre el periodo", () => {
    const s = portfolioSeries(holdings, history);
    expect(periodReturn(s, 24)).toBeNull();
  });

  it("sparkPoints produce pares x,y dentro del viewBox", () => {
    const s = portfolioSeries(holdings, history);
    const pts = sparkPoints(s, 300, 90).split(" ");
    expect(pts.length).toBe(4);
    for (const p of pts) { const [x, y] = p.split(",").map(Number); expect(x).toBeGreaterThanOrEqual(0); expect(x).toBeLessThanOrEqual(300); expect(y).toBeGreaterThanOrEqual(0); expect(y).toBeLessThanOrEqual(90); }
  });
});
