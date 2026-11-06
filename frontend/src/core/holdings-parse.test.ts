import { describe, expect, it } from "vitest";
import { normalizeHoldings, parseCsv } from "./holdings-parse";

describe("parseCsv", () => {
  it("maneja comillas y comas internas", () => {
    const m = parseCsv('a,b\n"Apple, Inc.",0.07\nNVDA,0.06\n');
    expect(m).toEqual([["a", "b"], ["Apple, Inc.", "0.07"], ["NVDA", "0.06"]]);
  });
});

describe("normalizeHoldings", () => {
  it("detecta columnas, normaliza % a fracción y marca completo", () => {
    const csv = [
      "Fund preamble line", "as of 2026-11-05",
      "Name,Ticker,Weight,Sector",
      "Apple Inc,AAPL,7.0,Information Technology",
      "Nvidia,NVDA,6.5,Information Technology",
      "Microsoft,MSFT,6.0,Information Technology",
      "Rest,REST,80.5,Various",
    ].join("\n");
    const r = normalizeHoldings(parseCsv(csv));
    expect(r.columns.ticker?.toLowerCase()).toBe("ticker");
    const aapl = r.lines.find((l) => l.ticker === "AAPL")!;
    expect(aapl.weight).toBeCloseTo(0.07, 6);       // 7.0% -> 0.07
    expect(r.weightSum).toBeCloseTo(1.0, 6);
    expect(r.status).toBe("complete");
  });

  it("pesos ya en fracción no se dividen", () => {
    const csv = "Name,Ticker,Weight\nA,A,0.5\nB,B,0.5\n";
    const r = normalizeHoldings(parseCsv(csv));
    expect(r.weightSum).toBeCloseTo(1.0, 6);
    expect(r.lines[0].weight).toBeCloseTo(0.5, 6);
  });

  it("detecta efectivo como no-equity", () => {
    const csv = "Name,Ticker,Weight\nUSD Cash,,2\nApple,AAPL,98\n";
    const r = normalizeHoldings(parseCsv(csv));
    expect(r.lines.find((l) => l.name === "USD Cash")!.assetClass).toBe("cash");
  });

  it("sin columna de peso => parcial", () => {
    const csv = "Name,Ticker\nApple,AAPL\n";
    const r = normalizeHoldings(parseCsv(csv));
    expect(r.status).toBe("partial");
  });

  it("company_key desde CUSIP (6) o ticker", () => {
    const csv = "Name,Ticker,Weight,CUSIP\nApple,AAPL,100,037833100\n";
    const r = normalizeHoldings(parseCsv(csv));
    expect(r.lines[0].companyKey).toBe("037833");
  });
});
