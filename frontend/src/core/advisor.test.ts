// Pruebas del motor determinístico del Investment Advisor (vitest, CI).
// Cubren las 10 correcciones: límite cartera-total vs nueva compra, ETF no-sector,
// asignación por diversificación (no por score), redondeo exacto del presupuesto,
// ranking separado de asignación, cumplimiento residual, alternativas, datos faltantes,
// gate sin capital, y procedencia de datos.
import { describe, expect, it } from "vitest";
import { buildAdvice, type Constraints, type Holding, type ScanInfo } from "./advisor";

const fac = (v = 50, q = 50, g = 50, m = 50, lr = 50) =>
  ({ value: v, quality: q, growth: g, momentum: m, low_risk: lr });

const scan = (ticker: string, composite: number, sector = "Tech", tags: string[] = []): ScanInfo =>
  ({ ticker, sector, composite, factors: fac(), tags });

const h = (
  ticker: string, mv: number | null, weight: number,
  sector: string | null = "Tech", assetClass: string | null = "equity"
): Holding => ({ ticker, name: ticker, sector, assetClass, marketValue: mv, weight, priceAsOf: "2026-11-01" });

const C: Constraints = { maxWeightAsset: 0.25, maxWeightSector: 0.4 };

describe("diagnóstico de concentración", () => {
  it("marca un activo que supera el límite por activo", () => {
    const r = buildAdvice([h("NVDA", 4000, 0.8, "Semis"), h("KO", 1000, 0.2, "Staples")],
      [scan("NVDA", 70, "Semis")], 0, C);
    const red = r.diagnostics.find((d) => d.kind === "reduce" && d.ticker === "NVDA");
    expect(red).toBeTruthy();
    expect(red!.justification.join(" ")).toContain("80.0%");
  });

  it("marca sobreexposición sectorial", () => {
    const r = buildAdvice([h("NVDA", 3000, 0.6, "Semis"), h("AVGO", 2000, 0.4, "Semis")], [], 0, C);
    expect(r.diagnostics.some((d) => d.kind === "trim_sector")).toBe(true);
  });

  it("NO trata un ETF como sector económico", () => {
    // QQQ al 80% dispara concentración por ACTIVO, pero no por SECTOR.
    const r = buildAdvice([h("QQQ", 4000, 0.8, null, "etf"), h("KO", 1000, 0.2, "Staples")], [], 0, C);
    expect(r.diagnostics.some((d) => d.kind === "trim_sector")).toBe(false);
    expect(r.diagnostics.some((d) => d.kind === "reduce" && d.ticker === "QQQ")).toBe(true);
  });
});

describe("ranking de oportunidades (separado de la asignación)", () => {
  it("propone no-tenencias con score alto y excluye las que ya tienes", () => {
    const r = buildAdvice([h("KO", 1000, 1, "Staples")],
      [scan("MU", 80), scan("MSFT", 72), scan("KO", 40, "Staples")], 0, C);
    const tickers = r.ideas.map((i) => i.ticker);
    expect(tickers).toContain("MU");
    expect(tickers).not.toContain("KO");
    expect(r.ideas[0].ticker).toBe("MU"); // ordenado por score
  });
});

describe("asignación por diversificación (no por score)", () => {
  it("reparte en partes IGUALES, no en proporción al score, cuando el tope no limita", () => {
    // caps holgados: dos candidatas con scores distintos deben recibir el MISMO monto.
    const loose: Constraints = { maxWeightAsset: 0.9, maxWeightSector: 0.9 };
    const r = buildAdvice([h("KO", 1000, 1, "Staples")], [scan("MU", 90), scan("MSFT", 66)], 3000, loose);
    const mu = r.allocation.items.find((i) => i.ticker === "MU")!;
    const msft = r.allocation.items.find((i) => i.ticker === "MSFT")!;
    expect(mu).toBeTruthy(); expect(msft).toBeTruthy();
    expect(Math.abs(mu.amount - msft.amount)).toBeLessThanOrEqual(1); // iguales (±1 por redondeo)
  });

  it("respeta el tope por activo (peso resultante) con una sola candidata fuerte", () => {
    const r = buildAdvice([h("KO", 1000, 1, "Staples")], [scan("MU", 90)], 3000, C);
    const mu = r.allocation.items.find((i) => i.ticker === "MU");
    expect(mu).toBeTruthy();
    expect(mu!.amount).toBeLessThanOrEqual(1000 + 1); // cap = 25% de (1000+3000) = 1000
    expect(r.allocation.cashLeftover).toBe(2000);
  });

  it("conserva EXACTAMENTE el presupuesto (enteros) aunque no divida parejo", () => {
    const loose: Constraints = { maxWeightAsset: 0.9, maxWeightSector: 0.9 };
    const r = buildAdvice([h("KO", 1000, 1, "Staples")],
      [scan("MU", 80), scan("MSFT", 75), scan("AMD", 70)], 1000, loose);
    const sum = r.allocation.items.reduce((a, i) => a + i.amount, 0);
    for (const it of r.allocation.items) expect(Number.isInteger(it.amount)).toBe(true);
    expect(sum + r.allocation.cashLeftover).toBe(1000); // invariante exacta
  });

  it("si nada cumple las reglas, recomienda liquidez", () => {
    const r = buildAdvice([h("KO", 1000, 1, "Staples")], [scan("KO", 40, "Staples")], 3000, C);
    expect(r.allocation.items).toHaveLength(0);
    expect(r.allocation.note.toLowerCase()).toContain("liquidez");
    expect(r.allocation.cashLeftover).toBe(3000);
  });

  it("sin capital (cash<=0) NO da montos específicos (gate)", () => {
    const r = buildAdvice([h("KO", 1000, 1, "Staples")], [scan("MU", 80)], 0, C);
    expect(r.allocation.blocked).toBeTruthy();
    expect(r.allocation.items).toHaveLength(0);
  });
});

describe("cumplimiento residual (no afirmar que cumple si no cumple)", () => {
  it("reporta que la concentración previa PERSISTE tras aportar capital nuevo", () => {
    const r = buildAdvice([h("NVDA", 4000, 0.8, "Semis"), h("KO", 1000, 0.2, "Staples")],
      [scan("NVDA", 70, "Semis"), scan("MU", 80), scan("MSFT", 75)], 3000, C);
    expect(r.compliance.ok).toBe(false);
    expect(r.compliance.remaining.join(" ")).toContain("NVDA");
  });
});

describe("alternativas y datos faltantes", () => {
  it("siempre ofrece mantener liquidez como alternativa", () => {
    const r = buildAdvice([h("KO", 1000, 1, "Staples")], [scan("MU", 80)], 3000, C);
    expect(r.alternatives.join(" ").toLowerCase()).toContain("liquidez");
  });

  it("muestra datos faltantes: tenencia sin precio", () => {
    const r = buildAdvice([h("KO", null, 0, "Staples"), h("MU", 1000, 1, "Semis")], [], 0, C);
    expect(r.dataGaps.join(" ")).toContain("KO");
  });
});

describe("timing determinístico (sin predicción)", () => {
  it("sugiere escalonar si el monto es grande vs. la cartera", () => {
    const r = buildAdvice([h("KO", 1000, 1, "Staples")], [scan("MU", 80)], 3000, C);
    expect(r.timing.join(" ").toLowerCase()).toContain("tramos");
  });
});

describe("decisiones priorizadas (vocabulario completo)", () => {
  it("una posición sobre el límite genera REDUCIR como prioridad 1", () => {
    const r = buildAdvice([h("NVDA", 4000, 0.8, "Semis"), h("KO", 1000, 0.2, "Staples")],
      [scan("NVDA", 70, "Semis")], 0, C);
    expect(r.decisions[0].action).toBe("REDUCIR");
    expect(r.decisions[0].ticker).toBe("NVDA");
    expect(r.decisions[0].priority).toBe(1);
    expect(r.decisions[0].suggestedDeltaUsd!).toBeLessThan(0); // recorte
  });

  it("con capital y candidata fuerte propone COMPRAR", () => {
    const r = buildAdvice([h("KO", 1000, 1, "Staples")], [scan("MU", 85)], 3000, C);
    expect(r.decisions.some((d) => d.action === "COMPRAR" && d.ticker === "MU")).toBe(true);
  });

  it("una posición ínfima genera VENDER (higiene)", () => {
    const r = buildAdvice([h("BIG", 9900, 0.99, "Tech"), h("STUB", 100, 0.01, "Tech")], [], 0, C);
    expect(r.decisions.some((d) => d.action === "VENDER" && d.ticker === "STUB")).toBe(true);
  });

  it("cartera equilibrada sin capital: termina en MANTENER o NO_HACER_NADA, nunca vacío", () => {
    // 5 posiciones de 20% en sectores distintos: dentro del límite por activo y sin stubs.
    const hs = [
      h("A", 2000, 0.2, "Tech"), h("B", 2000, 0.2, "Staples"), h("C", 2000, 0.2, "Energy"),
      h("D", 2000, 0.2, "Health"), h("E", 2000, 0.2, "Finance"),
    ];
    const r = buildAdvice(hs, [], 0, C);
    expect(r.decisions.length).toBeGreaterThanOrEqual(1);
    expect(r.decisions.every((d, i) => d.priority === i + 1)).toBe(true);
    expect(["MANTENER", "NO_HACER_NADA"]).toContain(r.decisions[r.decisions.length - 1].action);
  });

  it("usa el modelo de riesgo: REDUCIR por riesgo dominante aunque el peso esté dentro del límite", () => {
    const risk = {
      annVol: 0.3, effectiveN: 2, hhi: 0.5, probLoss12m: 0.3,
      contrib: [{ ticker: "VOL", weightPct: 0.2, riskPct: 0.6 }, { ticker: "CALM", weightPct: 0.8, riskPct: 0.4 }],
    };
    const r = buildAdvice([h("VOL", 2000, 0.2, "Tech"), h("CALM", 8000, 0.8, "Staples")], [], 0, C, undefined, risk);
    expect(r.decisions.some((d) => d.action === "REDUCIR" && d.ticker === "VOL")).toBe(true);
  });

  it("tope de 5 decisiones", () => {
    const hs = Array.from({ length: 10 }, (_, i) => h(`T${i}`, 100, 0.001, "Tech")); // 10 stubs
    const r = buildAdvice(hs, [], 0, C);
    expect(r.decisions.length).toBeLessThanOrEqual(5);
  });
});
