import { describe, expect, it } from "vitest";
import { fairValueDCF, type FundamentalsPayload, type HistoryRecord } from "./valuation";
import {
  rawRevenueCagr, g1Evidence, pathA, runDcfPath, robustBaseFcf, fairValueV2, V2_PARAMS,
} from "./valuation.v2";

// Construye un payload mínimo desde (año, ingresos, fcf). netDebt opcional.
function payload(rows: Array<[number, number, number]>, shares = 10, netDebt = 0): FundamentalsPayload {
  const annual: HistoryRecord[] = rows.map(([y, rev, fcf]) => ({
    period_end: `${y}-12-31`, revenue: rev, net_income: null, operating_income: null,
    ocf: null, capex: null, fcf, cash: null, gross_debt: null, net_debt: netDebt,
    op_margin: null, net_margin: null,
  }));
  return { diluted_shares: shares, net_debt: netDebt, currency: "USD",
    history: { currency: "USD", annual } } as unknown as FundamentalsPayload;
}
const flat = (n: number, rev: number, margin: number, startY = 2019): Array<[number, number, number]> =>
  Array.from({ length: n }, (_, i) => [startY + i, rev, rev * margin]);

describe("v2 · A — compresión de crecimiento g1Evidence", () => {
  it("≤ umbral: sin cambio", () => {
    expect(g1Evidence(0.10)).toBeCloseTo(0.10, 6);
    expect(g1Evidence(0.18)).toBeCloseTo(0.18, 6);
  });
  it("extremo: admite >18% pero comprime (no cap plano ni 30% arbitrario)", () => {
    const g = g1Evidence(0.67);
    expect(g).toBeGreaterThan(0.18);   // admite más que el viejo tope
    expect(g).toBeLessThan(0.40);      // pero comprime el 67% real
    expect(g).toBeLessThan(0.67);
  });
  it("monotónica y asintótica (no explota con CAGR absurdos)", () => {
    expect(g1Evidence(1.5)).toBeGreaterThan(g1Evidence(0.67));
    expect(g1Evidence(5.0)).toBeLessThan(0.45);
  });
});

describe("v2 · A — sendero pathA (desaceleración explícita)", () => {
  it("empieza en g1 y termina en terminal", () => {
    const p = pathA(0.34, 0.025, 10);
    expect(p[0]).toBeCloseTo(0.34, 6);
    expect(p[9]).toBeCloseTo(0.025, 6);
  });
  it("alto crecimiento: estrictamente decreciente (no extrapola el CAGR)", () => {
    const p = pathA(0.34, 0.025, 10);
    for (let i = 1; i < p.length; i++) expect(p[i]).toBeLessThan(p[i - 1]);
    expect(p[4]).toBeCloseTo(V2_PARAMS.midCycle, 6); // mid-cycle al año 5
  });
  it("bajo crecimiento (≤10%): idéntico al fade lineal V1", () => {
    const g1 = 0.05, gT = 0.025, n = 10;
    const p = pathA(g1, gT, n);
    for (let t = 1; t <= n; t++) expect(p[t - 1]).toBeCloseTo(g1 + (gT - g1) * (t - 1) / (n - 1), 9);
  });
});

describe("v2 · B — normalización robusta", () => {
  it("márgenes estables ⇒ elige MEDIA", () => {
    const n = robustBaseFcf(payload(flat(4, 100, 0.20)).history!.annual!)!;
    expect(n.pick).toBe("media");
    expect(n.chosen).toBeCloseTo(0.20, 6);
  });
  it("outlier bajo sin tendencia ⇒ elige MEDIANA y supera a la media arrastrada", () => {
    // margenes 20/5/20/20 (outlier bajo en el medio, no monótono)
    const rows: Array<[number, number, number]> = [[2022, 100, 20], [2023, 100, 5], [2024, 100, 20], [2025, 100, 20]];
    const n = robustBaseFcf(payload(rows).history!.annual!)!;
    expect(n.pick).toBe("mediana");
    expect(n.chosen).toBeGreaterThan(n.candidates.media);
  });
  it("tendencia clara al alza ⇒ elige RECIENTE", () => {
    const rows: Array<[number, number, number]> = [[2022, 100, 5], [2023, 100, 12], [2024, 100, 18], [2025, 100, 22]];
    const n = robustBaseFcf(payload(rows).history!.annual!)!;
    expect(n.pick).toBe("reciente");
  });
  it("guarda: el margen elegido nunca supera el máximo observado", () => {
    const rows: Array<[number, number, number]> = [[2022, 100, 5], [2023, 100, 60], [2024, 100, 6], [2025, 100, 7]];
    const n = robustBaseFcf(payload(rows).history!.annual!)!;
    expect(n.chosen).toBeLessThanOrEqual(Math.max(...n.margins));
  });
});

describe("v2 · runDcfPath", () => {
  it("devuelve valor positivo y finito; rechaza tasa ≤ terminal", () => {
    const r = runDcfPath(100, 10, pathA(0.10, 0.025), 0.025, 0.095)!;
    expect(r.perShare).toBeGreaterThan(0);
    expect(Number.isFinite(r.perShare)).toBe(true);
    expect(runDcfPath(100, 10, pathA(0.10, 0.03), 0.03, 0.02)).toBeNull();
  });
});

describe("v2 · regresión — no infla indiscriminadamente (controles vs crecimiento)", () => {
  const v1ps = (f: FundamentalsPayload) => fairValueDCF(f, null, null).base!.run.perShare;
  const v2ps = (f: FundamentalsPayload) => fairValueV2(f).base!.perShare;

  it("CONTROL maduro (CAGR ~4%, márgenes estables): V2 ≈ V1 (±3%)", () => {
    // ingresos 100→~117 en 5 años, margen FCF estable 20%
    const rows: Array<[number, number, number]> = [
      [2021, 100, 20], [2022, 104, 20.8], [2023, 108, 21.6], [2024, 112, 22.4], [2025, 116, 23.2],
    ];
    const f = payload(rows);
    const ratio = v2ps(f) / v1ps(f);
    expect(ratio).toBeGreaterThan(0.97);
    expect(ratio).toBeLessThan(1.03);
  });

  it("CRECIMIENTO real (CAGR ~60%, márgenes estables altos): A eleva V2 por encima de V1", () => {
    const rows: Array<[number, number, number]> = [
      [2021, 100, 40], [2022, 160, 64], [2023, 256, 102.4], [2024, 410, 164], [2025, 656, 262.4],
    ];
    const f = payload(rows);
    expect(v2ps(f)).toBeGreaterThan(v1ps(f) * 1.1); // el tope 18% mordía: A lo corrige
  });

  it("NORMALIZACIÓN (CAGR 0, un año outlier bajo): B eleva vía mediana/reciente, A neutro", () => {
    // revenue plano (A no aplica), margen 5/20/20/20 → media arrastrada
    const rows: Array<[number, number, number]> = [[2022, 100, 5], [2023, 100, 20], [2024, 100, 20], [2025, 100, 20]];
    const f = payload(rows);
    const v2 = fairValueV2(f);
    expect(v2.g1!).toBeLessThanOrEqual(V2_PARAMS.lowGrowthBypass); // A neutro
    expect(v2.normalization!.pick).not.toBe("media");
    expect(v2ps(f)).toBeGreaterThan(v1ps(f)); // B corrige el arrastre del outlier
  });

  it("bandera de deuda neta: se reporta, NO se resta del equity", () => {
    const f = payload(flat(4, 100, 0.20), 10, 50);
    const v2 = fairValueV2(f);
    expect(v2.netDebtRatio!).toBeGreaterThan(0); // reportada
    // equity no penalizado por deuda (mismo que sin deuda): base no cambia por netDebt
    const f0 = payload(flat(4, 100, 0.20), 10, 0);
    expect(fairValueV2(f).base!.perShare).toBeCloseTo(fairValueV2(f0).base!.perShare, 6);
  });
});
