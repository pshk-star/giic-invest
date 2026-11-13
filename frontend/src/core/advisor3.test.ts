import { describe, it, expect } from "vitest";
import { buildAdvisor3, type Adv3Input } from "./advisor3";

// Cartera real (fixture): 3 acciones + ETF + efectivo, con retornos alineados.
function baseInput(): Adv3Input {
  const r = (seed: number) => Array.from({ length: 40 }, (_, k) => Math.sin(seed + k) * 0.02);
  return {
    positions: [
      { ticker: "NVDA", sector: "Tech", country: "US", currency: "USD", assetClass: "equity", marketValue: 4000, weight: 0.40 },
      { ticker: "KO", sector: "Staples", country: "US", currency: "USD", assetClass: "equity", marketValue: 2000, weight: 0.20 },
      { ticker: "TSM", sector: "Tech", country: "TW", currency: "USD", assetClass: "equity", marketValue: 1500, weight: 0.15 },
      { ticker: "SPY", sector: "ETF", country: "US", currency: "USD", assetClass: "etf", marketValue: 1500, weight: 0.15 },
    ],
    cash: 1000,
    contribution: 3000,
    returns: { NVDA: r(1).map((x) => x * 1.6), KO: r(5).map((x) => x * 0.4), TSM: r(2).map((x) => x * 1.2), SPY: r(3).map((x) => x * 0.6) },
    valuation: {
      NVDA: { productiveMargin: -0.30, productiveConfidence: "alta", priceComparable: true },   // muy sobrevalorada
      KO: { productiveMargin: 0.18, productiveConfidence: "media", priceComparable: true },       // infravalorada, confianza media
      TSM: { productiveMargin: null, productiveConfidence: null, fcffMargin: 0.40, fcffConfidence: "baja", priceComparable: true }, // solo FCFF baja
      SPY: { productiveMargin: null, productiveConfidence: null, priceComparable: true },
    },
    quality: { NVDA: { eligible: true, fresh: true }, KO: { eligible: true, fresh: true }, TSM: { eligible: true, fresh: true }, SPY: { eligible: true, fresh: true } },
    constraints: { maxPositionWeight: 0.45, maxSectorWeight: 0.50, minMarginToBuy: 0.10 },
  };
}

describe("Advisor 3.0", () => {
  it("posición: muy sobrevalorada con confianza alta => REDUCIR/VENDER", () => {
    const r = buildAdvisor3(baseInput());
    const nvda = r.positionDecisions.find((d) => d.ticker === "NVDA")!;
    expect(["REDUCIR", "VENDER"]).toContain(nvda.action);
    expect(nvda.marginSource).toBe("productivo");
  });

  it("F12 (Codex P0): metodología bloqueada NO genera REDUCIR/VENDER por Fair Value", () => {
    // Misma cartera (NVDA margen −30%), pero barrera global activa (methodologyValidated:false).
    const r = buildAdvisor3({ ...baseInput(), methodologyValidated: false });
    const nvda = r.positionDecisions.find((d) => d.ticker === "NVDA")!;
    expect(nvda.action).toBe("REVISAR");                 // bloqueado ⇒ no se concluye por FV
    expect(nvda.trimAmount == null || nvda.trimAmount === 0).toBe(true);  // sin recorte cuantificado por FV
  });

  it("posición: FCFF experimental de baja confianza NO desplaza el FV productivo (=> REVISAR, no COMPRAR)", () => {
    const r = buildAdvisor3(baseInput());
    const tsm = r.positionDecisions.find((d) => d.ticker === "TSM")!;
    expect(tsm.action).toBe("REVISAR");                 // sin FV productivo + FCFF baja => sin conclusión
    expect(tsm.marginSource).not.toBe("productivo");
  });

  it("guardrail: margen positivo (FCFF baja confianza) NO habilita COMPRAR en la asignación", () => {
    const r = buildAdvisor3(baseInput());
    const deployed = r.allocation.options.flatMap((o) => o.items.map((i) => i.ticker));
    expect(deployed).not.toContain("TSM");              // TSM solo tiene FCFF baja => no es candidato
  });

  it("conservación de capital: Σ importes + efectivo == aporte, EXACTO, en toda opción", () => {
    const r = buildAdvisor3(baseInput());
    for (const o of r.allocation.options) {
      const sum = o.items.reduce((s, i) => s + i.amount, 0) + o.cashKept;
      expect(sum).toBe(3000);
    }
  });

  it("opción todo-efectivo (ESPERAR) siempre disponible", () => {
    const r = buildAdvisor3(baseInput());
    expect(r.allocation.options.some((o) => o.id === "efectivo")).toBe(true);
  });

  it("riesgo marginal: cada opción reporta vol sobre la cartera resultante COMPLETA", () => {
    const r = buildAdvisor3(baseInput());
    for (const o of r.allocation.options) expect(typeof o.volAfter).toBe("number");
    // KO (infravalorada, confianza media, productiva) sí es candidata => alguna opción la despliega
    const anyKO = r.allocation.options.some((o) => o.items.some((i) => i.ticker === "KO"));
    expect(anyKO).toBe(true);
  });

  it("consistencia: dos decisiones separadas; ETF se evalúa por rol, no por DCF", () => {
    const r = buildAdvisor3(baseInput());
    const spy = r.positionDecisions.find((d) => d.ticker === "SPY")!;
    expect(["MANTENER", "REVISAR"]).toContain(spy.action);  // vehículo, nunca por margen
  });

  it("datos ausentes: sin valoración => REVISAR, con explicación de condición de cambio", () => {
    const inp = baseInput();
    inp.valuation.KO = { productiveMargin: null, productiveConfidence: null, priceComparable: true };
    const r = buildAdvisor3(inp);
    const ko = r.positionDecisions.find((d) => d.ticker === "KO")!;
    expect(ko.action).toBe("REVISAR");
    expect(ko.explain.condicionesCambio.length).toBeGreaterThan(0);
  });

  it("explicabilidad: cada recomendación trae motivos/datos/riesgos/condiciones", () => {
    const r = buildAdvisor3(baseInput());
    for (const d of r.positionDecisions) {
      expect(d.explain.motivos.length).toBeGreaterThan(0);
      expect(d.explain.datosModelos.length).toBeGreaterThan(0);
      expect(d.explain.condicionesCambio.length).toBeGreaterThan(0);
    }
    expect(r.guardrails.length).toBeGreaterThan(0);
  });

  // ---------- P2.1.1 — Validación de decisiones ----------

  it("P2.1.1 VENDER exige corroboración: sobrevaloración fuerte + confianza + FCFF mismo lado + sin desacuerdo", () => {
    const inp = baseInput();
    inp.valuation.NVDA = { productiveMargin: -0.40, productiveConfidence: "alta", fcffMargin: -0.35, fcffConfidence: "media", priceComparable: true };
    const nvda = buildAdvisor3(inp).positionDecisions.find((d) => d.ticker === "NVDA")!;
    expect(nvda.action).toBe("VENDER");
  });

  it("P2.1.1 desacuerdo de MAGNITUD atenúa VENDER→REDUCIR (incertidumbre, no venta total)", () => {
    const inp = baseInput();
    // caso real NVDA: productivo -49%, FCFF -18%, brecha 0.31 ≥ 0.25 => desacuerdo material de magnitud
    inp.valuation.NVDA = { productiveMargin: -0.49, productiveConfidence: "alta", fcffMargin: -0.18, fcffConfidence: "media", priceComparable: true };
    const nvda = buildAdvisor3(inp).positionDecisions.find((d) => d.ticker === "NVDA")!;
    expect(nvda.action).toBe("REDUCIR");
    expect(nvda.explain.riesgos.join(" ")).toMatch(/desacuerdo/i);
  });

  it("P2.1.1 desacuerdo DIRECCIONAL (productivo caro vs FCFF barato) => REVISAR, no se concluye", () => {
    const inp = baseInput();
    inp.valuation.NVDA = { productiveMargin: -0.30, productiveConfidence: "alta", fcffMargin: 0.20, fcffConfidence: "media", priceComparable: true };
    const nvda = buildAdvisor3(inp).positionDecisions.find((d) => d.ticker === "NVDA")!;
    expect(nvda.action).toBe("REVISAR");
  });

  it("P2.1.1 la concentración NUNCA produce VENDER por sí sola (solo REDUCIR por riesgo)", () => {
    const inp = baseInput();
    // NVDA valorada razonable (margen 0) pero top-contribuyente de riesgo y sector sobre el límite
    inp.valuation.NVDA = { productiveMargin: 0.0, productiveConfidence: "media", priceComparable: true };
    const nvda = buildAdvisor3(inp).positionDecisions.find((d) => d.ticker === "NVDA")!;
    expect(nvda.action).not.toBe("VENDER");
    expect(nvda.action).toBe("REDUCIR");
    expect(nvda.explain.motivos.join(" ")).toMatch(/riesgo/i);
  });

  it("P2.1.1 contrafactual: a MENOR concentración, misma valoración, la acción no se agrava a VENDER", () => {
    const hi = baseInput();   // NVDA sobrevalorada -0.30 alta, sin FCFF => REDUCIR por valoración
    const base = buildAdvisor3(hi).positionDecisions.find((d) => d.ticker === "NVDA")!;
    const lo = baseInput();
    lo.positions = lo.positions.map((p) => p.ticker === "NVDA" ? { ...p, marketValue: 1500, weight: 0.18 } : p);
    const less = buildAdvisor3(lo).positionDecisions.find((d) => d.ticker === "NVDA")!;
    const rank = (a: string) => ["MANTENER", "REVISAR", "REDUCIR", "VENDER"].indexOf(a);
    expect(rank(less.action)).toBeLessThanOrEqual(rank(base.action));  // menos concentración no endurece
    expect(less.action).not.toBe("VENDER");
  });

  it("P2.1.1 contrafactual: a MAYOR confianza fundamental, la decisión concluye (deja de ser REVISAR)", () => {
    const inp = baseInput();
    // solo FCFF baja => REVISAR; al dar FV productivo con confianza suficiente, concluye
    inp.valuation.TSM = { productiveMargin: 0.14, productiveConfidence: "media", fcffMargin: 0.40, fcffConfidence: "baja", priceComparable: true };
    const tsm = buildAdvisor3(inp).positionDecisions.find((d) => d.ticker === "TSM")!;
    expect(tsm.action).not.toBe("REVISAR");
    expect(tsm.marginSource).toBe("productivo");
  });

  it("P2.1.1 contrafactual: aportes de distinto tamaño => despliegue monótono y conservación exacta", () => {
    const mk = (c: number) => buildAdvisor3({ ...baseInput(), contribution: c });
    for (const c of [0, 1000, 3000, 5000]) {
      const r = mk(c);
      for (const o of r.allocation.options) {
        expect(o.items.reduce((s, i) => s + i.amount, 0) + o.cashKept).toBe(c);  // conservación exacta
      }
    }
    const dep = (c: number) => { const r = mk(c); const o = r.allocation.options.find((x) => x.id === r.allocation.chosen)!; return o.items.reduce((s, i) => s + i.amount, 0); };
    expect(dep(5000)).toBeGreaterThanOrEqual(dep(1000));   // más aporte no despliega menos
    expect(dep(0)).toBe(0);                                 // sin aporte, no se inventa inversión
  });

  it("P2.1.1 asignación compara alternativas: efectivo + (valor/diversificar) + ETF diversificador", () => {
    const r = buildAdvisor3(baseInput());
    const ids = r.allocation.options.map((o) => o.id);
    expect(ids).toContain("efectivo");                      // ESPERAR siempre disponible
    expect(ids).toContain("etf");                           // ETF en cartera => opción de diversificación
    const etf = r.allocation.options.find((o) => o.id === "etf")!;
    expect(etf.items.every((i) => /diversif/i.test(i.reason))).toBe(true);  // justificada por diversificación, no margen
  });

  it("P2.1.1 sin acciones con margen pero con concentración elevada => ETF diversificador (no ESPERAR ciego)", () => {
    const inp = baseInput();
    inp.valuation.KO = { productiveMargin: 0.05, productiveConfidence: "media", priceComparable: true }; // <umbral => no candidata
    const r = buildAdvisor3(inp);
    expect(r.allocation.chosen).toBe("etf");
    expect(r.allocation.note).toMatch(/concentrad|diversif/i);
  });

  it("P2.1.1 sin oportunidades y sin problema de concentración => ESPERAR es la elección válida", () => {
    const inp = baseInput();
    inp.valuation.KO = { productiveMargin: 0.05, productiveConfidence: "media", priceComparable: true };
    // aplanar concentración: pesos equilibrados y sin sector sobre el límite
    inp.positions = [
      { ticker: "KO", sector: "Staples", country: "US", currency: "USD", assetClass: "equity", marketValue: 2500, weight: 0.25 },
      { ticker: "SPY", sector: "ETF", country: "US", currency: "USD", assetClass: "etf", marketValue: 2500, weight: 0.25 },
      { ticker: "TSM", sector: "Tech", country: "TW", currency: "USD", assetClass: "equity", marketValue: 2500, weight: 0.25 },
      { ticker: "KHC", sector: "Health", country: "US", currency: "USD", assetClass: "equity", marketValue: 2500, weight: 0.25 },
    ];
    inp.returns = { ...inp.returns, KHC: inp.returns.KO.map((x) => -x) };
    inp.valuation.KHC = { productiveMargin: 0.02, productiveConfidence: "media", priceComparable: true };
    inp.quality.KHC = { eligible: true, fresh: true };
    const r = buildAdvisor3(inp);
    expect(r.allocation.chosen).toBe("efectivo");
  });
});
