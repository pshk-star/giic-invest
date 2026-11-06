import { describe, expect, it } from "vitest";
import { toBase, valueFund, type FundMove } from "./funds";

const m = (o: Partial<FundMove>): FundMove => ({ side: "buy", quantity: null, price: null, fees: 0, ...o });

describe("valueFund", () => {
  it("participaciones netas, valor y conversión a base", () => {
    const moves = [m({ side: "buy", quantity: 100, price: 10 }), m({ side: "buy", quantity: 50, price: 12 })];
    const v = valueFund(moves, 13, "2026-11-05", "MXN", 0.05); // 150 part × 13 = 1950 MXN
    expect(v.units).toBe(150);
    expect(v.netContributedFundCcy).toBe(100 * 10 + 50 * 12); // 1600
    expect(v.valueFundCcy).toBe(1950);
    expect(v.valueBase).toBeCloseTo(1950 * 0.05, 9); // 97.5 USD
    expect(v.gainFundCcy).toBe(1950 - 1600);
    expect(v.stale).toBe(false);
  });

  it("venta parcial reduce participaciones", () => {
    const v = valueFund([m({ side: "buy", quantity: 100, price: 10 }), m({ side: "sell", quantity: 40, price: 11 })],
      11, "2026-11-05", "MXN", 1);
    expect(v.units).toBe(60);
    expect(v.valueFundCcy).toBe(660);
  });

  it("sin NAV => stale y valor nulo", () => {
    const v = valueFund([m({ side: "buy", quantity: 10, price: 10 })], null, null, "MXN", 0.05);
    expect(v.stale).toBe(true);
    expect(v.valueFundCcy).toBeNull();
    expect(v.valueBase).toBeNull();
  });

  it("sin tipo de cambio => valueBase nulo pero valueFundCcy existe", () => {
    const v = valueFund([m({ side: "buy", quantity: 10, price: 10 })], 12, "2026-11-05", "MXN", null);
    expect(v.valueFundCcy).toBe(120);
    expect(v.valueBase).toBeNull();
  });
});

describe("toBase", () => {
  const fx = { USD: 1, MXN: 0.05379, EUR: 1.1224 };
  it("misma moneda", () => expect(toBase(100, "USD", "USD", fx)).toBe(100));
  it("MXN -> USD", () => expect(toBase(1000, "MXN", "USD", fx)).toBeCloseTo(53.79, 2));
  it("EUR -> MXN", () => expect(toBase(100, "EUR", "MXN", fx)).toBeCloseTo(100 * (1.1224 / 0.05379), 2));
  it("moneda desconocida => null", () => expect(toBase(100, "JPY", "USD", fx)).toBeNull());
});
