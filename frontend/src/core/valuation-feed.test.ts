import { describe, it, expect } from "vitest";
import { latestValuations, valuationInput } from "./valuation-feed";
import { governingValuation, passesValueGate } from "./valuation-policy";

// Fila del feed: payload con run_kind/run_id + id de identidad (orden de publicación). data.ts entrega id-desc.
const cv = (ticker: string, status: string, extra: any = {}) => ({
  ticker, status, modelos: [{modelo: "motor_v2", status, fair_value_usd: 308.8, margen_seguridad_pct: -23.8,
    confianza: "baja", metodologia_validada: false, ...extra}]});
const row = (ticker: string, id: number, run_id: string, run_kind: string, payload: any) =>
  ({ticker, id, payload: {...payload, run_id, run_kind}});

describe("governing publication consumer (P0-A: vigencia por corrida completa)", () => {
  const good: any = cv("TSM", "en_revision");

  it("latest invalidation supersedes a positive old FV without legacy fallback", () => {
    // baseline completa (id 1, good) + revaloración parcial posterior (id 2, no_valorable)
    const data = latestValuations([
      row("TSM", 2, "B", "partial", {ticker: "TSM", status: "no_valorable", modelos: []}),
      row("TSM", 1, "A", "full", good)]);
    const v = valuationInput(data.resultados.TSM);
    expect(governingValuation(v).blocked).toBe(true);
    expect(governingValuation(v).margin).toBeNull();
    expect(passesValueGate(v, .1)).toBe(false);
  });

  it("valid snapshot keeps scenarios and has one governing source", () => {
    const data = latestValuations([row("TSM", 1, "A", "full", good)]);
    expect(governingValuation(valuationInput(data.resultados.TSM)).source).toBe("motor_v2");
    expect(governingValuation(valuationInput(data.resultados.TSM)).margin).toBeCloseTo(-.238, 12);
  });

  it("malformed latest data and absent data fail closed", () => {
    const data = latestValuations([
      row("TSM", 2, "B", "partial", {ticker: "TSM", modelos: "bad"}),
      row("TSM", 1, "A", "full", good)]);
    expect(data.resultados.TSM.precio).toBeNull();
    expect(valuationInput(data.resultados.TSM).engineStatus).toBe("no_valorable");
    expect(passesValueGate(valuationInput(undefined), .1)).toBe(false);
  });

  it("sin corrida completa: nada gobierna (fail closed) aunque existan parciales", () => {
    const data = latestValuations([row("TSM", 3, "P", "partial", good)]);
    expect(data.resultados.TSM).toBeUndefined();
  });

  it("ticker omitido de la última corrida completa NO se resucita de una corrida anterior", () => {
    // Parcial vieja publicó AAA (id 1). La corrida COMPLETA (id 2) solo trae BBB. AAA no debe sobrevivir.
    const data = latestValuations([
      row("BBB", 2, "FULL", "full", cv("BBB", "en_revision")),
      row("AAA", 1, "OLD", "partial", cv("AAA", "consistente"))]);
    expect(data.resultados.BBB).toBeDefined();
    expect(data.resultados.AAA).toBeUndefined();   // invalidado: no está en la última corrida completa
  });

  it("corrida parcial posterior actualiza solo su ticker; los demás conservan la baseline completa", () => {
    const data = latestValuations([
      row("AAA", 3, "PART", "partial", cv("AAA", "no_valorable", {status: "no_valorable", fair_value_usd: null})),
      row("BBB", 2, "FULL", "full", cv("BBB", "en_revision")),
      row("AAA", 2, "FULL", "full", cv("AAA", "en_revision"))]);
    expect(data.resultados.AAA.status).toBe("no_valorable");   // actualizado por la parcial posterior
    expect(data.resultados.BBB.status).toBe("en_revision");    // intacto desde la baseline completa
  });
});
