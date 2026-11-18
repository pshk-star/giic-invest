import { describe, it, expect } from "vitest";
import { opportunityDisclosure } from "./opportunity-disclosure";

describe("P0-B: /opportunities (scan factorial) nunca es accionable fuera de la política gobernante", () => {
  it("metodología bloqueada: no accionable y aviso de bloqueo explícito", () => {
    const d = opportunityDisclosure(false);
    expect(d.actionable).toBe(false);
    expect(d.blocked).toBe(true);
    expect(d.tone).toBe("warn");
    expect(d.banner).toMatch(/NO son recomendaciones de compra/i);
    expect(d.banner).toMatch(/bloqueada/i);
  });

  it("aun con metodología validada, el scan factorial por sí solo NO es accionable", () => {
    const d = opportunityDisclosure(true);
    expect(d.actionable).toBe(false);   // señal independiente: nunca habilita compra por sí misma
    expect(d.blocked).toBe(false);
  });
});
