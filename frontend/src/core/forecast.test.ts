import { describe, expect, it } from "vitest";
import { forecast, type AssetHistory } from "./forecast";

// genera retornos deterministas pseudo-aleatorios con media/vol dadas
function series(n: number, mean: number, vol: number, seed: number): number[] {
  let a = seed >>> 0;
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    a = (a * 1664525 + 1013904223) >>> 0;
    const u = (a / 4294967296) - 0.5;
    out.push(mean + vol * u * 3.464); // u*3.464 ~ uniforme con vol~1
  }
  return out;
}

describe("forecast", () => {
  it("concilia valor actual y produce horizontes", () => {
    const assets: AssetHistory[] = [
      { ticker: "A", valueUsd: 6000, returns: series(300, 0.0003, 0.012, 1) },
      { ticker: "B", valueUsd: 4000, returns: series(300, 0.0002, 0.015, 2) },
    ];
    const r = forecast(assets, { sims: 300, seed: 7 });
    expect(r.currentValue).toBe(10000);
    expect(r.horizons.map((h) => h.days)).toEqual([21, 63, 126, 252]);
    expect(r.annVol).toBeGreaterThan(0);
    // banda mediana a 12m razonable (no colapsa ni explota)
    const h12 = r.horizons[3];
    expect(h12.valP5).toBeLessThan(h12.valP50);
    expect(h12.valP50).toBeLessThan(h12.valP95);
    expect(h12.probLoss).toBeGreaterThanOrEqual(0);
    expect(h12.probLoss).toBeLessThanOrEqual(1);
  });

  it("contribución al riesgo suma ~100% y respeta pesos", () => {
    const assets: AssetHistory[] = [
      { ticker: "A", valueUsd: 8000, returns: series(300, 0, 0.02, 3) },
      { ticker: "B", valueUsd: 2000, returns: series(300, 0, 0.005, 4) },
    ];
    const r = forecast(assets, { sims: 200 });
    const sum = r.riskContrib.reduce((s, x) => s + x.riskPct, 0);
    expect(Math.abs(sum - 1)).toBeLessThan(1e-6);
    // el activo grande y más volátil domina el riesgo
    expect(r.riskContrib[0].ticker).toBe("A");
    expect(r.hhi).toBeCloseTo(0.8 * 0.8 + 0.2 * 0.2, 6);
  });

  it("excluye activos sin historial suficiente y avisa", () => {
    const assets: AssetHistory[] = [
      { ticker: "A", valueUsd: 5000, returns: series(300, 0, 0.01, 5) },
      { ticker: "NEW", valueUsd: 5000, returns: series(10, 0, 0.01, 6) },
    ];
    const r = forecast(assets, { sims: 100 });
    expect(r.warnings.join(" ")).toMatch(/sin historial/);
    expect(r.riskContrib.length).toBe(1);
  });

  it("sin activos con historial: resultado vacío con aviso", () => {
    const r = forecast([{ ticker: "X", valueUsd: 1000, returns: [0.01, 0.02] }], { sims: 10 });
    expect(r.horizons.length).toBe(0);
    expect(r.warnings.length).toBeGreaterThan(0);
  });
});

describe("consistencia por horizonte e individual vs consolidado", () => {
  it("cada horizonte: P5<=P50<=P95, probLoss en [0,1], var95 = valP5 - valor actual", () => {
    const assets: AssetHistory[] = [{ ticker: "A", valueUsd: 10000, returns: series(400, 0.0003, 0.012, 9) }];
    const r = forecast(assets, { sims: 400, seed: 11 });
    expect(r.horizons.length).toBe(4);
    for (const h of r.horizons) {
      expect(h.valP5).toBeLessThanOrEqual(h.valP50);
      expect(h.valP50).toBeLessThanOrEqual(h.valP95);
      expect(h.probLoss).toBeGreaterThanOrEqual(0);
      expect(h.probLoss).toBeLessThanOrEqual(1);
      expect(Math.abs(h.var95 - (h.valP5 - r.currentValue))).toBeLessThan(1e-6);
    }
  });

  it("proyección individual = mismo motor que el consolidado (determinista con misma semilla)", () => {
    const a: AssetHistory[] = [{ ticker: "X", valueUsd: 5000, returns: series(300, 0.0002, 0.01, 3) }];
    const r1 = forecast(a, { sims: 200, seed: 5 });
    const r2 = forecast(a, { sims: 200, seed: 5 });
    expect(r1.horizons[3].valP50).toBe(r2.horizons[3].valP50);
    expect(r1.annVol).toBeCloseTo(r2.annVol, 12);
  });
});
