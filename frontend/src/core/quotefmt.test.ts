import { describe, expect, it } from "vitest";
import { classifyQuote } from "./quotefmt";

const now = Date.parse("2026-11-05T18:00:00Z");

describe("clasificación de cotización", () => {
  it("mercado abierto y reciente => en vivo retrasado (nunca 'tiempo real')", () => {
    const r = classifyQuote("2026-11-05T17:55:00Z", "REGULAR", true, now);
    expect(r.freshness).toBe("live");
    expect(r.label).toContain("retrasado");
  });

  it("mercado cerrado => último cierre", () => {
    const r = classifyQuote("2026-11-04T21:00:00Z", "CLOSED", true, now);
    expect(r.freshness).toBe("close");
  });

  it("cotización vieja (> 36 h) => desactualizado", () => {
    const r = classifyQuote("2026-11-02T18:00:00Z", "CLOSED", true, now);
    expect(r.freshness).toBe("stale");
  });

  it("sin hora => stale, sin inventar", () => {
    expect(classifyQuote(null, "REGULAR", true, now).freshness).toBe("stale");
  });
});
