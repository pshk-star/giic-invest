import { describe, expect, it } from "vitest";
import { annualize, simpleReturn, twr, xirr } from "./returns";

describe("xirr (money-weighted)", () => {
  it("−1000 hoy, +1100 en 1 año => ~10%", () => {
    const r = xirr([{ date: "2025-01-01", amount: -1000 }, { date: "2026-01-01", amount: 1100 }]);
    expect(r).not.toBeNull();
    expect(Math.abs((r as number) - 0.10)).toBeLessThan(1e-3);
  });

  it("flujos múltiples con valor terminal", () => {
    // compra 1000, aporta 500 a los 6m, vale 1800 al año -> TIR positiva razonable
    const r = xirr([
      { date: "2025-01-01", amount: -1000 },
      { date: "2025-07-01", amount: -500 },
      { date: "2026-01-01", amount: 1800 },
    ]);
    expect(r).not.toBeNull();
    expect((r as number)).toBeGreaterThan(0.15);
    expect((r as number)).toBeLessThan(0.35);
  });

  it("sin signo mixto => null", () => {
    expect(xirr([{ date: "2025-01-01", amount: -100 }, { date: "2026-01-01", amount: -50 }])).toBeNull();
    expect(xirr([{ date: "2025-01-01", amount: 1 }])).toBeNull();
  });

  it("pérdida => TIR negativa", () => {
    const r = xirr([{ date: "2025-01-01", amount: -1000 }, { date: "2026-01-01", amount: 800 }]);
    expect(r).not.toBeNull();
    expect((r as number)).toBeLessThan(0);
  });
});

describe("twr y utilidades", () => {
  it("twr encadena geométricamente", () => {
    expect(Math.abs(twr([0.1, 0.1]) - 0.21) < 1e-9).toBe(true);
    expect(twr([0.1, -0.1])).toBeCloseTo(-0.01, 9); // 1.1*0.9-1
  });
  it("annualize", () => {
    expect(annualize(0.21, 365)).toBeCloseTo(0.21, 6);
    expect(annualize(0.1, 182.5)).toBeCloseTo(0.21, 2); // medio año al 10% -> ~21% anual
    expect(annualize(-1, 365)).toBeNull();
  });
  it("simpleReturn", () => {
    expect(simpleReturn(1000, 1200)).toBeCloseTo(0.2, 9);
    expect(simpleReturn(0, 100)).toBeNull();
  });
});
