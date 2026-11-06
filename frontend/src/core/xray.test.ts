import { describe, expect, it } from "vitest";
import { effectiveExposure, type EtfWeight, type PortfolioHolding } from "./xray";

describe("effectiveExposure (Portfolio X-Ray)", () => {
  const holdings: PortfolioHolding[] = [
    { ticker: "NVDA", isEtf: false, valueUsd: 1000 },
    { ticker: "VOO", isEtf: true, valueUsd: 2000 },
    { ticker: "QQQ", isEtf: true, valueUsd: 1000 },
  ];
  const weights: EtfWeight[] = [
    { etf: "VOO", ticker: "NVDA", weight: 0.07, name: "NVIDIA" },
    { etf: "VOO", ticker: "AAPL", weight: 0.06, name: "Apple" },
    { etf: "QQQ", ticker: "NVDA", weight: 0.08, name: "NVIDIA" },
    { etf: "QQQ", ticker: "MSFT", weight: 0.09, name: "Microsoft" },
  ];

  it("suma exposición directa + indirecta por empresa, con fuentes", () => {
    const r = effectiveExposure(holdings, weights);
    const nvda = r.byCompany.find((c) => c.ticker === "NVDA")!;
    // directa 1000 + VOO 2000*0.07=140 + QQQ 1000*0.08=80 = 1220
    expect(nvda.direct).toBe(1000);
    expect(nvda.indirect).toBeCloseTo(220, 6);
    expect(nvda.total).toBeCloseTo(1220, 6);
    expect(nvda.sources.map((s) => s.via).sort()).toEqual(["QQQ", "VOO", "directo"]);
    expect(r.byCompany[0].ticker).toBe("NVDA"); // ordenado por total desc
  });

  it("peso no identificado va a desconocido (no se atribuye a acciones)", () => {
    const r = effectiveExposure(holdings, weights);
    // VOO identificó 13% (260), QQQ 17% (170); resto desconocido
    // VOO residual 2000*0.87=1740 ; QQQ residual 1000*0.83=830 => 2570
    expect(r.unknownUsd).toBeCloseTo(1740 + 830, 6);
    expect(r.totalUsd).toBe(4000);
    expect(r.identifiedPct).toBeCloseTo((4000 - 2570) / 4000, 6);
  });

  it("clase no-equity (efectivo/derivado) cuenta como desconocido", () => {
    const r = effectiveExposure(
      [{ ticker: "XYZ", isEtf: true, valueUsd: 100 }],
      [{ etf: "XYZ", ticker: "USD-CASH", weight: 0.1, assetClass: "cash" },
       { etf: "XYZ", ticker: "AAA", weight: 0.9, name: "AAA Corp" }],
    );
    expect(r.unknownUsd).toBeCloseTo(10, 6);       // la parte cash
    expect(r.byCompany.find((c) => c.ticker === "AAA")!.total).toBeCloseTo(90, 6);
  });

  it("ETF sin holdings => su valor es exposición desconocida y se reporta", () => {
    const r = effectiveExposure(
      [{ ticker: "SMH", isEtf: true, valueUsd: 500 }], [],
    );
    expect(r.unknownUsd).toBe(500);
    expect(r.etfsWithoutHoldings).toEqual(["SMH"]);
    expect(r.identifiedPct).toBe(0);
  });

  it("sin doble conteo: identificado + desconocido = total", () => {
    const r = effectiveExposure(holdings, weights);
    expect(r.identifiedUsd + r.unknownUsd).toBeCloseTo(r.totalUsd, 6);
  });
});
