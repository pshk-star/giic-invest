// Pruebas del motor determinístico del Investment Advisor (vitest, CI).
import { describe, expect, it } from "vitest";
import { buildAdvice, type Holding, type ScanInfo } from "./advisor";

const f = (v = 50, q = 50, g = 50, m = 50, lr = 50) =>
  ({ value: v, quality: q, growth: g, momentum: m, low_risk: lr });

const scan = (ticker: string, composite: number, sector = "Tech", tags: string[] = []): ScanInfo =>
  ({ ticker, sector, composite, factors: f(), tags });

const C = { maxWeightAsset: 0.25, maxWeightSector: 0.4 };

describe("diagnóstico de concentración", () => {
  it("marca un activo que supera el límite por activo", () => {
    const holdings: Holding[] = [
      { ticker: "NVDA", name: "NVIDIA", sector: "Semis", marketValue: 4000, weight: 0.8 },
      { ticker: "KO", name: "Coca-Cola", sector: "Staples", marketValue: 1000, weight: 0.2 },
    ];
    const r = buildAdvice(holdings, [scan("NVDA", 70, "Semis")], 0, C);
    const red = r.diagnostics.find((d) => d.kind === "reduce" && d.ticker === "NVDA");
    expect(red).toBeTruthy();
    expect(red!.justification.join(" ")).toContain("80.0%");
  });

  it("marca sobreexposición sectorial", () => {
    const holdings: Holding[] = [
      { ticker: "NVDA", name: "N", sector: "Semis", marketValue: 3000, weight: 0.6 },
      { ticker: "AVGO", name: "A", sector: "Semis", marketValue: 2000, weight: 0.4 },
    ];
    const r = buildAdvice(holdings, [], 0, C);
    expect(r.diagnostics.some((d) => d.kind === "trim_sector")).toBe(true);
  });
});

describe("ideas nuevas desde el scanner", () => {
  it("propone no-tenencias con score alto y explica el porqué", () => {
    const holdings: Holding[] = [{ ticker: "KO", name: "KO", sector: "Staples", marketValue: 1000, weight: 1 }];
    const r = buildAdvice(holdings, [scan("MU", 80), scan("MSFT", 72), scan("KO", 40, "Staples")], 0, C);
    const tickers = r.ideas.map((i) => i.ticker);
    expect(tickers).toContain("MU");
    expect(tickers).not.toContain("KO");        // ya la tiene
    expect(r.ideas[0].justification.join(" ")).toContain("Score");
  });
});

describe("asignación determinística de capital", () => {
  it("reparte por score respetando el límite por activo y excluye el sobreconcentrado", () => {
    const holdings: Holding[] = [
      { ticker: "NVDA", name: "N", sector: "Semis", marketValue: 4000, weight: 0.8 },
      { ticker: "KO", name: "KO", sector: "Staples", marketValue: 1000, weight: 0.2 },
    ];
    const r = buildAdvice(holdings, [scan("NVDA", 70, "Semis"), scan("MU", 80), scan("MSFT", 75)], 3000, C);
    const alloc = r.allocation;
    // no asigna a NVDA (ya sobre el límite) ni a KO (score 40 < 65)
    expect(alloc.items.find((i) => i.ticker === "NVDA")).toBeFalsy();
    // invierte en MU y MSFT
    expect(alloc.items.map((i) => i.ticker).sort()).toEqual(["MSFT", "MU"]);
    // total invertido no excede el cash
    const sum = alloc.items.reduce((a, i) => a + i.amount, 0);
    expect(sum).toBeLessThanOrEqual(3000);
    // ningún activo supera el 25% del total resultante
    for (const it of alloc.items) expect(it.newWeight).toBeLessThanOrEqual(0.25 + 1e-6);
  });

  it("si nada cumple las reglas, recomienda liquidez", () => {
    const holdings: Holding[] = [{ ticker: "KO", name: "KO", sector: "Staples", marketValue: 1000, weight: 1 }];
    const r = buildAdvice(holdings, [scan("KO", 40, "Staples")], 3000, C);
    expect(r.allocation.items).toHaveLength(0);
    expect(r.allocation.note.toLowerCase()).toContain("liquidez");
    expect(r.allocation.cashLeftover).toBe(3000);
  });

  it("respeta el tope por activo incluso con una sola candidata muy fuerte", () => {
    const holdings: Holding[] = [{ ticker: "KO", name: "KO", sector: "Staples", marketValue: 1000, weight: 1 }];
    const r = buildAdvice(holdings, [scan("MU", 90)], 3000, C);
    // denom = 1000+3000 = 4000; cap por activo = 25% = 1000
    const mu = r.allocation.items.find((i) => i.ticker === "MU");
    expect(mu).toBeTruthy();
    expect(mu!.amount).toBeLessThanOrEqual(1000 + 1);
    expect(r.allocation.cashLeftover).toBeGreaterThanOrEqual(2000 - 1);
  });
});

describe("timing determinístico (sin predicción)", () => {
  it("sugiere escalonar si el monto es grande vs. la cartera", () => {
    const holdings: Holding[] = [{ ticker: "KO", name: "KO", sector: "Staples", marketValue: 1000, weight: 1 }];
    const r = buildAdvice(holdings, [scan("MU", 80)], 3000, C);
    expect(r.timing.join(" ").toLowerCase()).toContain("tramos");
  });
});
