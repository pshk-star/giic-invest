import { describe, expect, it } from "vitest";
import {
  computeWacc, projectFcff, evToEquity, valueScenario, reverseG1, sensitivity,
  fairValueFcff, MARKET_2026_11_10 as M, FCFF_ASSUMPTIONS,
  type CompanyBase, type Assumptions, type Ccy,
} from "./valuation.fcff";

function base(over: Partial<CompanyBase> = {}): CompanyBase {
  return { ticker: "AAA", ccy: "USD" as Ccy, period: "2025-12-31", revenue: 100_000,
    ebitMargin0: 0.40, netDebt: 0, shares: 1000, adr: 1, eligibility: "eligible", ...over };
}
const A: Assumptions = { beta: 1.2, kd: 0.05, dv: 0.08, taxNorm: 0.14, salesToCapital: 1.5,
  g1: 0.12, marginTerminal: 0.35, roicTerminal: 0.20 };

describe("fcff · WACC por moneda (identidades y no-reutilización de Ke USD)", () => {
  it("Ke = rf + β·(ERP+CRP); WACC con estructura de capital e impuestos", () => {
    const w = computeWacc(A, "USD", M);
    expect(w.ke).toBeCloseTo(0.041 + 1.2 * 0.045, 6);
    expect(w.wacc).toBeCloseTo(0.92 * w.ke + 0.08 * 0.05 * (1 - 0.14), 6);
  });
  it("flujos TWD usan rf TWD + CRP Taiwán, NO rf USD", () => {
    const w = computeWacc(A, "TWD", M);
    expect(w.rf).toBe(0.015); expect(w.crp).toBe(0.0085);
    expect(w.ke).toBeCloseTo(0.015 + 1.2 * (0.045 + 0.0085), 6);
  });
});

describe("fcff · proyección e identidades", () => {
  it("FCFF = NOPAT − reinversión; ingresos componen; EV = PV(FCFF)+PV(terminal)", () => {
    const w = computeWacc(A, "USD", M);
    const p = projectFcff(base(), A, 0.041, 0.35, w.wacc);
    const r0 = p.rows[0];
    expect(r0.fcff).toBeCloseTo(r0.nopat - r0.reinvest, 6);
    expect(r0.revenue).toBeCloseTo(100_000 * (1 + 0.12), 6);     // g1 en año 1
    expect(p.ev).toBeCloseTo(p.pvFcff + p.pvTerminal, 4);
    expect(p.rows[9].g).toBeCloseTo(0.041, 6);                   // fade a terminal en año 10
  });
  it("terminal consistente: reinversión_T = gT/ROIC_T", () => {
    const w = computeWacc(A, "USD", M);
    const p = projectFcff(base(), A, 0.041, 0.35, w.wacc);
    expect(p.reinvestTerminal).toBeCloseTo(0.041 / 0.20, 6);
  });
  it("rechaza WACC ≤ gT (no permite terminal explosivo)", () => {
    expect(() => projectFcff(base(), A, 0.10, 0.35, 0.09)).toThrow();
  });
  it("reinversión alta ⇒ ROIC coherente (g = RR·ROIC): capital-intensivo deprime FCFF cercano", () => {
    const w = computeWacc(A, "USD", M);
    const heavy = projectFcff(base(), { ...A, salesToCapital: 0.8 }, 0.041, 0.35, w.wacc);
    const light = projectFcff(base(), { ...A, salesToCapital: 3.0 }, 0.041, 0.35, w.wacc);
    expect(heavy.rows[0].fcff).toBeLessThan(light.rows[0].fcff);   // más reinversión → menos FCFF cercano
  });
});

describe("fcff · puente EV→equity, moneda/ADR y dilución", () => {
  it("equity = EV − deuda neta (caja neta suma); FV/acción", () => {
    const b = evToEquity(base({ netDebt: -5000 }), 100_000, M);
    expect(b.equity).toBe(105_000);
    expect(b.perShareLocal).toBeCloseTo(105, 6);
  });
  it("ADR TWD: convierte por FX y ratio ADR", () => {
    const b = evToEquity(base({ ccy: "TWD", adr: 5, shares: 1000 }), 1_000_000, M);
    // equity 1,000,000 TWD / 1000 = 1000 TWD/ord ×(1/32.80)×5 = por ADR
    expect(b.perShareUsd).toBeCloseTo(1000 * (1 / 32.80) * 5, 6);
  });
  it("SBC NO se doble-cuenta: ya está gastado en el margen EBIT, no se resta otra vez", () => {
    // mismo netDebt ⇒ el FV no cambia por 'añadir' SBC (no hay campo que lo reste de nuevo)
    const w = computeWacc(A, "USD", M);
    const p = projectFcff(base(), A, 0.041, 0.35, w.wacc);
    const b1 = evToEquity(base(), p.ev, M);
    const b2 = evToEquity(base(), p.ev, M);
    expect(b1.perShareUsd).toBe(b2.perShareUsd);
  });
});

describe("fcff · sensibilidad, reverse DCF", () => {
  it("rejilla WACC×gT: mayor WACC baja el valor; mayor gT lo sube", () => {
    const grid = sensitivity(base(), A, M);
    expect(grid.length).toBe(3); expect(grid[0].length).toBe(3);
    expect(grid[2][1]).toBeLessThan(grid[0][1]);   // WACC +1% < WACC −1%
    expect(grid[1][2]).toBeGreaterThan(grid[1][0]); // gT +0.5pp > gT −0.5pp
  });
  it("reverse DCF: g1 que iguala el precio es monótono (precio mayor ⇒ g1 mayor)", () => {
    const g_lo = reverseG1(base(), A, M, 100);
    const g_hi = reverseG1(base(), A, M, 300);
    expect(g_hi).toBeGreaterThan(g_lo);
  });
});

describe("fcff · confianza y datos faltantes (sin cifra artificial)", () => {
  it("na / ineligible ⇒ no disponible (no una cifra)", () => {
    expect(fairValueFcff(base({ eligibility: "na" }), A, M, 100).available).toBe(false);
    expect(fairValueFcff(base({ eligibility: "ineligible" }), A, M, 100).available).toBe(false);
  });
  it("degraded ⇒ confianza BAJA (menor confianza, no precisión falsa)", () => {
    const v = fairValueFcff(base({ eligibility: "degraded" }), A, M, 100);
    expect(v.available).toBe(true); expect(v.confidence).toBe("baja");
  });
  it("devuelve escenarios cons ≤ base ≤ opt y peso terminal reportado", () => {
    const v = fairValueFcff(base(), A, M, 100);
    expect(v.scenarios.conservador).toBeLessThanOrEqual(v.scenarios.base);
    expect(v.scenarios.base).toBeLessThanOrEqual(v.scenarios.optimista);
    expect(v.terminalWeight).toBeGreaterThan(0); expect(v.terminalWeight).toBeLessThan(1);
  });
});

describe("fcff · regresión con empresa madura (no infla)", () => {
  it("crecimiento bajo + margen estable ⇒ FV finito, peso terminal razonable", () => {
    const mature = base({ revenue: 100_000, ebitMargin0: 0.25 });
    const aMature: Assumptions = { ...A, g1: 0.04, marginTerminal: 0.25, salesToCapital: 1.0, roicTerminal: 0.12 };
    const v = fairValueFcff(mature, aMature, M, 50);
    expect(Number.isFinite(v.bridge.perShareUsd)).toBe(true);
    expect(v.bridge.perShareUsd).toBeGreaterThan(0);
    expect(v.terminalWeight).toBeLessThan(0.9);
  });
  it("las 5 tienen supuestos configurados", () => {
    for (const t of ["NVDA", "META", "NFLX", "TSM", "ASML"]) expect(FCFF_ASSUMPTIONS[t]).toBeTruthy();
  });
});
