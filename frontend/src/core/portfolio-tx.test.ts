// Pruebas de paridad del núcleo de transacciones (vitest, corre en CI).
import { describe, expect, it } from "vitest";
import { derivePositions, portfolioTotals, type Split, type Txn } from "./portfolio-tx";

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

describe("ajuste automático por split (NFLX 10:1, ex 2025-11-17)", () => {
  const nflxSplit: Split[] = [{ ticker: "NFLX", ratio: 10, ex_date: "2025-11-17" }];

  it("compra PRE-split: ×10 acciones, costo total intacto, sin P&L artificial", () => {
    // 2 @ 1000 antes del split; precio actual 110 (post-split).
    const pos = derivePositions(
      [tx({ ticker: "NFLX", side: "buy", quantity: 2, price: 1000, executed_at: "2025-06-01" })],
      { NFLX: { close: 110, as_of: "2026-11-05", currency: "USD" } }, {}, nflxSplit,
    );
    expect(pos[0].qty).toBe(20);                 // 2 × 10
    expect(pos[0].avgCost).toBeCloseTo(100, 6);  // 1000 ÷ 10
    expect(pos[0].investedExFees).toBeCloseTo(2000, 6); // costo total intacto (2×1000)
    expect(pos[0].marketValue).toBeCloseTo(2200, 6);    // 20 × 110
    expect(pos[0].unrealized).toBeCloseTo(200, 6);      // P&L real, no inflado por el split
  });

  it("compra POST-split (en/después del ex_date): NO se ajusta", () => {
    const pos = derivePositions(
      [tx({ ticker: "NFLX", side: "buy", quantity: 20, price: 100, executed_at: "2025-11-17" })],
      {}, {}, nflxSplit,
    );
    expect(pos[0].qty).toBe(20);
    expect(pos[0].avgCost).toBeCloseTo(100, 6);
  });

  it("mezcla PRE y POST split: cantidades y costo consistentes", () => {
    const pos = derivePositions([
      tx({ ticker: "NFLX", side: "buy", quantity: 1, price: 900, executed_at: "2025-01-10" }),   // -> 10 @ 90
      tx({ ticker: "NFLX", side: "buy", quantity: 10, price: 95, executed_at: "2026-02-01" }),    // post: 10 @ 95
    ], {}, {}, nflxSplit);
    expect(pos[0].qty).toBe(20);                       // 10 + 10
    expect(pos[0].investedExFees).toBeCloseTo(1850, 6); // 900 + 950, costo total intacto
    expect(pos[0].avgCost).toBeCloseTo(92.5, 6);
  });

  it("venta parcial PRE-split se calcula en acciones post-split", () => {
    const pos = derivePositions([
      tx({ ticker: "NFLX", side: "buy", quantity: 2, price: 1000, executed_at: "2025-06-01" }),  // 20 @ 100
      tx({ ticker: "NFLX", side: "sell", quantity: 1, price: 1200, executed_at: "2025-07-01" }), // vende 10 @ 120
    ], {}, {}, nflxSplit);
    expect(pos[0].qty).toBe(10);                     // quedan 10
    expect(pos[0].realized).toBeCloseTo(200, 6);     // 10 × (120 − 100)
  });

  it("no se aplica dos veces (idempotente): recalcular da el mismo resultado", () => {
    const t = [tx({ ticker: "NFLX", side: "buy", quantity: 2, price: 1000, executed_at: "2025-06-01" })];
    const a = derivePositions(t, {}, {}, nflxSplit);
    const b = derivePositions(t, {}, {}, nflxSplit);
    expect(a[0].qty).toBe(20); expect(b[0].qty).toBe(20);
  });

  it("dividendo (efectivo) NO se escala por split", () => {
    const pos = derivePositions([
      tx({ ticker: "NFLX", side: "buy", quantity: 2, price: 1000, executed_at: "2025-06-01" }),
      tx({ ticker: "NFLX", side: "dividend", amount: 50, executed_at: "2025-07-01" }),
    ], {}, {}, nflxSplit);
    expect(pos[0].dividends).toBeCloseTo(50, 6);      // 50, no 500
  });

  it("reverse split 1:10 (ratio 0.1) reduce acciones y sube costo/acción", () => {
    const pos = derivePositions(
      [tx({ ticker: "ZZ", side: "buy", quantity: 100, price: 2, executed_at: "2025-01-01" })],
      {}, {}, [{ ticker: "ZZ", ratio: 0.1, ex_date: "2025-06-01" }],
    );
    expect(pos[0].qty).toBeCloseTo(10, 6);            // 100 × 0.1
    expect(pos[0].avgCost).toBeCloseTo(20, 6);        // 2 ÷ 0.1
    expect(pos[0].investedExFees).toBeCloseTo(200, 6); // costo total intacto
  });
});
