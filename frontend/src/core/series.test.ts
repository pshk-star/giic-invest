import { describe, expect, it } from "vitest";
import { annualizedVol, maxDrawdown, periodReturn } from "./series";

describe("métricas de series", () => {
  it("retorno del período", () => {
    expect(periodReturn([100, 110])!).toBeCloseTo(0.1, 6);
    expect(periodReturn([100])).toBeNull();
  });

  it("máximo drawdown (negativo)", () => {
    // sube a 120, cae a 90 => dd pico-valle = 90/120-1 = -0.25
    expect(maxDrawdown([100, 120, 90, 100])!).toBeCloseTo(-0.25, 6);
    expect(maxDrawdown([100])).toBeNull();
  });

  it("volatilidad anualizada: 0 si la serie es plana", () => {
    expect(annualizedVol([100, 100, 100, 100])!).toBeCloseTo(0, 6);
  });

  it("volatilidad anualizada: positiva si hay variación", () => {
    const v = annualizedVol([100, 101, 99, 102, 98, 103])!;
    expect(v).toBeGreaterThan(0);
  });
});
