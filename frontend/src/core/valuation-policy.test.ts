import { describe, it, expect } from "vitest";
import { governingValuation, passesValueGate } from "./valuation-policy";

describe("P2.4 política de valoración única", () => {
  it("FV productivo es PRIMARIO cuando existe (el FCFF no lo desplaza)", () => {
    const g = governingValuation({ productiveMargin: 0.20, productiveConfidence: "media", fcffMargin: -0.40, fcffConfidence: "alta" }, { fcffFallback: true });
    expect(g.source).toBe("productivo");
    expect(g.margin).toBe(0.20);
    expect(g.tier).toBe("confiable");
  });

  it("sin FV productivo + FCFF suficiente + fallback ON => FCFF gobierna (experimental)", () => {
    const g = governingValuation({ productiveMargin: null, productiveConfidence: null, fcffMargin: 0.25, fcffConfidence: "media" }, { fcffFallback: true });
    expect(g.source).toBe("fcff_fallback");
    expect(g.margin).toBe(0.25);
    expect(g.tier).toBe("experimental");
    expect(passesValueGate({ productiveMargin: null, productiveConfidence: null, fcffMargin: 0.25, fcffConfidence: "media" }, 0.10, { fcffFallback: true })).toBe(true);
  });

  it("sin FV productivo + FCFF suficiente + fallback OFF => FCFF solo contexto (no gobierna)", () => {
    const v = { productiveMargin: null, productiveConfidence: null, fcffMargin: 0.25, fcffConfidence: "media" };
    const g = governingValuation(v, { fcffFallback: false });
    expect(g.source).toBe("fcff(contexto)");
    expect(passesValueGate(v, 0.10, { fcffFallback: false })).toBe(false);   // comportamiento histórico, reversible
  });

  it("FCFF de baja confianza NO gobierna aunque el fallback esté ON", () => {
    const v = { productiveMargin: null, productiveConfidence: null, fcffMargin: 0.30, fcffConfidence: "baja" };
    expect(passesValueGate(v, 0.10, { fcffFallback: true })).toBe(false);
    expect(governingValuation(v, { fcffFallback: true }).source).toBe("ninguno");
  });

  it("sin datos => insuficiente, sin margen (no se inventa)", () => {
    const g = governingValuation(undefined, { fcffFallback: true });
    expect(g.source).toBe("ninguno");
    expect(g.tier).toBe("insuficiente");
    expect(g.margin).toBeNull();
  });

  it("margen extremo (FV >> precio) degrada a confianza baja y NO respalda asignación", () => {
    const v = { productiveMargin: null, productiveConfidence: null, fcffMargin: 1.16, fcffConfidence: "media" as const };
    const g = governingValuation(v, { fcffFallback: true });
    expect(g.conf).toBe("baja");
    expect(g.tier).toBe("experimental");
    expect(passesValueGate(v, 0.10, { fcffFallback: true })).toBe(false);   // ADBE/PFE no entran a asignación
  });

  it("precio no comparable ignora el FV productivo", () => {
    const g = governingValuation({ productiveMargin: 0.20, productiveConfidence: "media", priceComparable: false });
    expect(g.source).not.toBe("productivo");
  });

  it("BARRERA: valoración FCFF en revisión NO pasa la criba aunque margen y confianza sean suficientes", () => {
    const v = { productiveMargin: null, productiveConfidence: null, fcffMargin: 0.28, fcffConfidence: "media" as const, reviewBlock: true, reviewReason: "crecimiento gratis" };
    const g = governingValuation(v, { fcffFallback: true });
    expect(g.blocked).toBe(true);
    expect(g.source).toBe("fcff_fallback");      // el FV se conserva (no se altera), pero bloqueado
    expect(g.margin).toBeCloseTo(0.28, 6);
    expect(passesValueGate(v, 0.10, { fcffFallback: true })).toBe(false);
  });

  it("BARRERA: no afecta a una valoración FCFF sin marca de revisión (sigue accionable)", () => {
    const v = { productiveMargin: null, productiveConfidence: null, fcffMargin: 0.28, fcffConfidence: "media" as const };
    expect(passesValueGate(v, 0.10, { fcffFallback: true })).toBe(true);
  });

  it("BARRERA: no bloquea al FV productivo (modelo no afectado por los hallazgos)", () => {
    const v = { productiveMargin: 0.20, productiveConfidence: "media" as const, fcffMargin: 0.28, fcffConfidence: "media" as const, reviewBlock: true };
    const g = governingValuation(v, { fcffFallback: true });
    expect(g.source).toBe("productivo");
    expect(g.blocked).toBeFalsy();
    expect(passesValueGate(v, 0.10, { fcffFallback: true })).toBe(true);
  });
});
