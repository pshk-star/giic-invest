import { describe, it, expect } from "vitest";
import {
  availableModels, productiveBlock, isRecommendationFree, confidenceTone, marginView, MODEL_LABEL,
  type CompanyValuation,
} from "./fundval";

const company: CompanyValuation = {
  ticker: "NVDA", ccy: "USD", precio: 177.2, gT_pct: 4.1,
  modelos: [
    { modelo: "DCF_productivo", fair_value_usd: 90, precio: 177.2, confianza: "producción",
      nota: "productivo", procedencia: { fecha: "2026-11-10", moneda: "USD" } },
    { modelo: "FCFF_GIIC", fair_value_usd: 145.26, precio: 177.2, margen_seguridad_pct: -18,
      confianza: "baja", wacc_pct: 10.05, peso_terminal_pct: 59.7, reverse_dcf_g1_pct: 35.6,
      escenarios: { conservador: 91, base: 145, optimista: 216 }, proyeccion_10a: [] },
    { modelo: "FCFF_corregido", disponible: false, motivo: "requiere serie reportada (EODHD)" },
    { modelo: "FCFF_combinado_consenso", disponible: false, motivo: "consenso no admitido",
      razones: ["moneda distinta"] },
  ],
  comparacion: { fair_values: { FCFF_GIIC: 145.26 }, explicacion: "..." },
};

describe("fundval (render-only helpers)", () => {
  it("parity: availableModels devuelve los FV del backend sin transformarlos", () => {
    const av = availableModels(company);
    expect(av.map((m) => m.modelo)).toEqual(["DCF_productivo", "FCFF_GIIC"]);
    expect(av.find((m) => m.modelo === "FCFF_GIIC")!.fair_value_usd).toBe(145.26); // sin recálculo
  });

  it("datos insuficientes: los modelos disponible:false se excluyen (no son recomendación)", () => {
    const av = availableModels(company);
    expect(av.some((m) => m.modelo === "FCFF_corregido")).toBe(false);
    expect(av.some((m) => m.modelo === "FCFF_combinado_consenso")).toBe(false);
  });

  it("regresión: el DCF productivo es passthrough (confianza 'producción', no experimental)", () => {
    const p = productiveBlock(company)!;
    expect(p.confianza).toBe("producción");
    expect(isRecommendationFree(company)).toBe(true);
  });

  it("confidenceTone mapea niveles", () => {
    expect(confidenceTone("alta")).toContain("emerald");
    expect(confidenceTone("baja")).toContain("rose");
    expect(MODEL_LABEL["FCFF_corregido"]).toContain("corregida");
  });

  it("#4: margen positivo con confianza BAJA no se pinta como señal de compra", () => {
    const low = marginView(49.6, "baja");       // NVDA combinado: +49.6% pero confianza baja
    expect(low.neutral).toBe(true);
    expect(low.cls).not.toContain("emerald");    // NO verde
    expect(low.label).toContain("no concluyente");
    const good = marginView(20, "media");        // margen positivo con confianza media => verde
    expect(good.neutral).toBe(false);
    expect(good.cls).toContain("emerald");
    const over = marginView(-30, "media");       // sobrevalorado => rose
    expect(over.cls).toContain("rose");
    expect(marginView(null, "media").label).toBe("—");
  });

  it("payload sin modelos disponibles no rompe (empresa recién creada)", () => {
    const empty: CompanyValuation = { ...company, modelos: [
      { modelo: "FCFF_GIIC", disponible: false, motivo: "sin datos" }] };
    expect(availableModels(empty)).toEqual([]);
  });
});
