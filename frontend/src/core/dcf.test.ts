import { describe, expect, it } from "vitest";
import { runDcf, fairValueDCF, type FundamentalsPayload, type HistoryRecord } from "./valuation";

const EMPTY: FundamentalsPayload = {
  pe_ttm: null, pe_forward: null, ev_ebitda: null, fcf_yield: null, roic: null, roe: null,
  rev_growth_yoy: null, eps_growth_yoy: null, net_margin: null, debt_to_equity: null, market_cap: null,
};

function hist(years: number, startRev: number, g: number, fcfMargin: number, netDebt: number): HistoryRecord[] {
  const out: HistoryRecord[] = [];
  for (let i = 0; i < years; i++) {
    const rev = startRev * Math.pow(1 + g, i);
    const fcf = rev * fcfMargin;
    out.push({
      period_end: `20${20 + i}-12-31`, revenue: rev, net_income: rev * 0.2,
      operating_income: rev * 0.25, ocf: fcf * 1.3, capex: fcf * 0.3, fcf,
      cash: 0, gross_debt: 0, net_debt: netDebt, op_margin: 0.25, net_margin: 0.2,
    });
  }
  return out;
}

function mkFund(over: Partial<FundamentalsPayload>, h: HistoryRecord[], ccy = "USD"): FundamentalsPayload {
  return { ...EMPTY, currency: ccy, diluted_shares: 1_000_000_000, net_debt: 0,
    history: { source: "EDGAR", currency: ccy, annual: h }, ...over };
}

describe("runDcf — identidades contables", () => {
  const a = { years: 10, g1: 0.1, gTerminal: 0.025, discount: 0.09 };
  it("EV = PV explícito + PV terminal; equity = EV − deuda neta; perShare = equity/acciones", () => {
    const r = runDcf(1000, 200, 50, a)!;
    expect(r.ev).toBeCloseTo(r.pvExplicit + r.pvTerminal, 6);
    expect(r.equity).toBeCloseTo(r.ev - 200, 6);
    expect(r.perShare).toBeCloseTo(r.equity / 50, 6);
    expect(r.terminalWeight).toBeCloseTo(r.pvTerminal / r.ev, 6);
  });
  it("caja neta (deuda neta < 0) aumenta el equity por encima del EV", () => {
    const r = runDcf(1000, -300, 50, a)!;
    expect(r.equity).toBeGreaterThan(r.ev);
  });
  it("rechaza supuestos inconsistentes (tasa ≤ terminal, FCF≤0, acciones≤0)", () => {
    expect(runDcf(1000, 0, 50, { ...a, gTerminal: 0.09 })).toBeNull();
    expect(runDcf(0, 0, 50, a)).toBeNull();
    expect(runDcf(1000, 0, 0, a)).toBeNull();
  });
  it("mayor tasa ⇒ menor valor; mayor crecimiento ⇒ mayor valor", () => {
    const lo = runDcf(1000, 0, 50, { ...a, discount: 0.08 })!;
    const hi = runDcf(1000, 0, 50, { ...a, discount: 0.11 })!;
    expect(hi.perShare).toBeLessThan(lo.perShare);
    const g1 = runDcf(1000, 0, 50, { ...a, g1: 0.05 })!;
    const g2 = runDcf(1000, 0, 50, { ...a, g1: 0.15 })!;
    expect(g2.perShare).toBeGreaterThan(g1.perShare);
  });
});

describe("fairValueDCF — escenarios y guardas", () => {
  it("construye 3 escenarios ordenados: conservador < base < optimista", () => {
    const f = mkFund({ diluted_shares: 1e9, net_debt: 0 }, hist(6, 1000, 0.12, 0.25, 0));
    const fv = fairValueDCF(f, 100, "USD");
    expect(fv.available).toBe(true);
    const [c, b, o] = fv.scenarios!;
    expect(c.run.perShare).toBeLessThan(b.run.perShare);
    expect(b.run.perShare).toBeLessThan(o.run.perShare);
    expect(fv.base!.name).toBe("Base");
  });

  it("sin FCF histórico suficiente (financiera) ⇒ no disponible", () => {
    const h = hist(6, 1000, 0.1, 0.25, 0).map((r) => ({ ...r, fcf: null, ocf: null, capex: null }));
    const fv = fairValueDCF(mkFund({}, h), 100, "USD");
    expect(fv.available).toBe(false);
    expect(fv.reason).toMatch(/financiera|insuficiente|≥3/i);
  });

  it("acciones diluidas ausentes ⇒ no disponible", () => {
    const fv = fairValueDCF(mkFund({ diluted_shares: null }, hist(6, 1000, 0.1, 0.25, 0)), 100, "USD");
    expect(fv.available).toBe(false);
    expect(fv.reason).toMatch(/acciones/i);
  });

  it("precio en otra moneda ⇒ margen no calculado (sin FX) y sin crecimiento implícito", () => {
    const fv = fairValueDCF(mkFund({}, hist(6, 1000, 0.1, 0.25, 0), "TWD"), 100, "USD");
    expect(fv.available).toBe(true);
    expect(fv.priceComparable).toBe(false);
    expect(fv.base!.marginVsPrice).toBeNull();
    expect(fv.impliedGrowth).toBeNull();
  });

  it("precio en moneda de reporte ⇒ margen y crecimiento implícito calculados y coherentes", () => {
    const f = mkFund({ diluted_shares: 1e9, net_debt: 0 }, hist(6, 1000, 0.12, 0.25, 0));
    const fv = fairValueDCF(f, 100, "USD");
    expect(fv.priceComparable).toBe(true);
    expect(fv.base!.marginVsPrice).not.toBeNull();
    expect(typeof fv.impliedGrowth).toBe("number");
    // el crecimiento implícito queda dentro de los límites de la bisección
    expect(fv.impliedGrowth!).toBeGreaterThanOrEqual(-0.15);
    expect(fv.impliedGrowth!).toBeLessThanOrEqual(0.60);
  });

  it("deuda neta desconocida ⇒ confianza no Alta y nota explícita", () => {
    const h = hist(6, 1000, 0.1, 0.25, 0).map((r) => ({ ...r, net_debt: null }));
    const fv = fairValueDCF(mkFund({ net_debt: null }, h), 100, "USD");
    expect(fv.available).toBe(true);
    expect(fv.confidenceNotes!.join(" ")).toMatch(/deuda neta/i);
  });

  it("sensibilidad: 9 celdas (3 tasas × 3 crecimientos terminales)", () => {
    const fv = fairValueDCF(mkFund({}, hist(6, 1000, 0.12, 0.25, 0)), 100, "USD");
    expect(fv.sensitivity!.length).toBe(9);
    expect(fv.sensitivity!.every((c) => typeof c.perShare === "number")).toBe(true);
  });
});
