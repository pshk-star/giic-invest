// Pruebas de paridad del núcleo de transacciones (vitest, corre en CI).
import { describe, expect, it } from "vitest";
import { derivePositions, portfolioTotals, type Txn } from "./portfolio-tx";

let idc = 0;
const tx = (p: Partial<Txn>): Txn => ({
  id: String(++idc), ticker: "NVDA", side: "buy", quantity: null, price: null,
  fees: 0, amount: null, currency: "USD", executed_at: "2026-01-15",
  created_at: String(idc), ...p,
});

describe("costo promedio ponderado", () => {
  it("10@120 + 5@140 => 15 acciones, avg 126.67 (sin comisiones)", () => {
    const pos = derivePositions([
      tx({ side: "buy", quantity: 10, price: 120, executed_at: "2026-01-15" }),
      tx({ side: "buy", quantity: 5, price: 140, executed_at: "2026-01-20" }),
    ]);
    expect(pos).toHaveLength(1);
    expect(pos[0].qty).toBe(15);
    expect(pos[0].avgCost).toBeCloseTo(126.666667, 4);
  });

  it("valor actual y P&L con precio de mercado", () => {
    const pos = derivePositions(
      [tx({ side: "buy", quantity: 15, price: 126.6667 })],
      { NVDA: { close: 150, as_of: "2026-11-05", currency: "USD" } }
    );
    expect(pos[0].marketValue).toBeCloseTo(2250, 2);
    expect(pos[0].unrealized).toBeCloseTo(2250 - 1900, 1);
    expect(pos[0].unrealizedPct).toBeCloseTo((2250 - 1900) / 1900, 4);
  });
});

describe("venta parcial (método del promedio)", () => {
  it("vende 5 de 15 @150: realized correcto, quedan 10 al mismo avg", () => {
    const pos = derivePositions([
      tx({ side: "buy", quantity: 10, price: 120, executed_at: "2026-01-15" }),
      tx({ side: "buy", quantity: 5, price: 140, executed_at: "2026-01-20" }),
      tx({ side: "sell", quantity: 5, price: 150, fees: 1, executed_at: "2026-02-01" }),
    ]);
    const p = pos[0];
    expect(p.qty).toBe(10);
    expect(p.avgCost).toBeCloseTo(126.666667, 4);           // promedio no cambia
    // realized = (150 - 126.6667)*5 - 1 = 116.666... - 1
    expect(p.realized).toBeCloseTo((150 - 126.666667) * 5 - 1, 2);
  });

  it("venta total deja la posición en 0 (no listada si no hay realized/div)", () => {
    const pos = derivePositions([
      tx({ side: "buy", quantity: 10, price: 100, executed_at: "2026-01-01" }),
      tx({ side: "sell", quantity: 10, price: 110, executed_at: "2026-02-01" }),
    ]);
    expect(pos).toHaveLength(1);         // se lista por el realized
    expect(pos[0].qty).toBe(0);
    expect(pos[0].realized).toBeCloseTo(100, 2);
  });
});

describe("totales de cartera", () => {
  it("suma valor, costo y marca precios faltantes", () => {
    const pos = derivePositions(
      [
        tx({ ticker: "NVDA", side: "buy", quantity: 10, price: 100 }),
        tx({ ticker: "QQQ", side: "buy", quantity: 5, price: 400 }),
      ],
      { NVDA: { close: 120, as_of: "2026-11-05", currency: "USD" } } // falta QQQ
    );
    const t = portfolioTotals(pos);
    expect(t.marketValue).toBeCloseTo(1200, 2);     // solo NVDA tiene precio
    expect(t.missingPrices).toContain("QQQ");
    expect(t.costBasis).toBeCloseTo(1000 + 2000, 2);
  });
});

describe("dividendos y splits", () => {
  it("dividendo en efectivo se acumula", () => {
    const pos = derivePositions([
      tx({ side: "buy", quantity: 10, price: 100 }),
      tx({ side: "dividend", amount: 25, executed_at: "2026-03-01" }),
    ]);
    expect(pos[0].dividends).toBe(25);
  });

  it("split 2:1 duplica cantidad y ajusta el costo promedio", () => {
    const pos = derivePositions([
      tx({ side: "buy", quantity: 10, price: 100, executed_at: "2026-01-01" }),
      tx({ side: "split", quantity: 2, executed_at: "2026-02-01" }),
    ]);
    expect(pos[0].qty).toBe(20);
    expect(pos[0].avgCost).toBeCloseTo(50, 6);
  });
});
