import { describe, it, expect } from "vitest";
import { latestValuations, valuationInput } from "./valuation-feed";
import { governingValuation, passesValueGate } from "./valuation-policy";

describe("governing publication consumer", () => {
  const good: any = {ticker:"TSM",status:"en_revision",modelos:[{modelo:"motor_v2",status:"en_revision",fair_value_usd:308.8,margen_seguridad_pct:-23.8,confianza:"baja",metodologia_validada:false}]};
  it("latest invalidation supersedes a positive old FV without legacy fallback", () => {
    const data = latestValuations([{ticker:"TSM",payload:{ticker:"TSM",status:"no_valorable",modelos:[]}}, {ticker:"TSM",payload:good}]);
    const v = valuationInput(data.resultados.TSM);
    expect(governingValuation(v).blocked).toBe(true);
    expect(governingValuation(v).margin).toBeNull();
    expect(passesValueGate(v, .1)).toBe(false);
  });
  it("valid snapshot keeps scenarios and has one governing source", () => {
    const data = latestValuations([{ticker:"TSM",payload:good}]);
    expect(governingValuation(valuationInput(data.resultados.TSM)).source).toBe("motor_v2");
    expect(governingValuation(valuationInput(data.resultados.TSM)).margin).toBeCloseTo(-.238, 12);
  });
  it("malformed latest data and absent data fail closed", () => {
    const data = latestValuations([{ticker:"TSM",payload:{ticker:"TSM",modelos:"bad"}}, {ticker:"TSM",payload:good}]);
    expect(data.resultados.TSM.precio).toBeNull();
    expect(valuationInput(data.resultados.TSM).engineStatus).toBe("no_valorable");
    expect(passesValueGate(valuationInput(undefined), .1)).toBe(false);
  });
});
