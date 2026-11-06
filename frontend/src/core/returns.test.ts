import { describe, expect, it } from "vitest";
import { annualize, investmentCashFlows, simpleReturn, twr, xirr, type TxnLike } from "./returns";

const tx = (o: Partial<TxnLike>): TxnLike => ({
  side: "buy", quantity: null, price: null, fees: 0, amount: null,
  currency: "USD", executed_at: "2025-01-01", ...o,
});

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

describe("investmentCashFlows — casos reproducibles (sin doble conteo)", () => {
  it("compras y ventas parciales + posición abierta (valor terminal)", () => {
    const txns = [
      tx({ side: "buy", quantity: 10, price: 100, executed_at: "2025-01-01" }),   // -1000
      tx({ side: "buy", quantity: 10, price: 120, executed_at: "2025-06-01" }),   // -1200
      tx({ side: "sell", quantity: 5, price: 150, executed_at: "2025-09-01" }),   // +750
    ];
    const b = investmentCashFlows(txns, 2500, "2026-01-01", "USD"); // 15 abiertas valen 2500
    expect(b.mixedCurrency).toBe(false);
    expect(b.flows.map((f) => f.amount)).toEqual([-1000, -1200, 750, 2500]);
    const r = xirr(b.flows);
    expect(r).not.toBeNull();
    expect((r as number)).toBeGreaterThan(0);
  });

  it("dividendos cuentan como entrada", () => {
    const b = investmentCashFlows([
      tx({ side: "buy", quantity: 10, price: 100, executed_at: "2025-01-01" }),
      tx({ side: "dividend", amount: 30, executed_at: "2025-07-01" }),
    ], 1050, "2026-01-01");
    expect(b.flows.map((f) => f.amount)).toEqual([-1000, 30, 1050]);
  });

  it("depósitos y retiros de efectivo se EXCLUYEN (no doble conteo)", () => {
    const b = investmentCashFlows([
      tx({ side: "deposit", amount: 5000, executed_at: "2025-01-01" }),
      tx({ side: "buy", quantity: 10, price: 100, executed_at: "2025-01-02" }),
      tx({ side: "withdrawal", amount: 200, executed_at: "2025-03-01" }),
      tx({ side: "split", quantity: 2, executed_at: "2025-04-01" }),
    ], 1200, "2026-01-01");
    // solo la compra y el valor terminal; depósito/retiro/split fuera
    expect(b.flows.map((f) => f.amount)).toEqual([-1000, 1200]);
  });

  it("comisiones restan al costo y al producto de venta", () => {
    const b = investmentCashFlows([
      tx({ side: "buy", quantity: 10, price: 100, fees: 5, executed_at: "2025-01-01" }),
      tx({ side: "sell", quantity: 10, price: 110, fees: 5, executed_at: "2025-06-01" }),
    ], 0, "2026-01-01");
    expect(b.flows.map((f) => f.amount)).toEqual([-1005, 1095]); // sin valor terminal (0)
  });

  it("multimoneda (MXN+USD) => mixedCurrency, sin flujos (requiere FX)", () => {
    const b = investmentCashFlows([
      tx({ side: "buy", quantity: 10, price: 100, currency: "USD" }),
      tx({ side: "buy", quantity: 100, price: 20, currency: "MXN" }),
    ], 5000, "2026-01-01", "USD");
    expect(b.mixedCurrency).toBe(true);
    expect(b.flows).toEqual([]);
  });

  it("cartera solo con efectivo (sin inversión) => sin flujos de inversión", () => {
    const b = investmentCashFlows([
      tx({ side: "deposit", amount: 1000, executed_at: "2025-01-01" }),
    ], 0, "2026-01-01");
    expect(b.flows).toEqual([]);
    expect(xirr(b.flows)).toBeNull();
  });
});
