// P0-B (Codex): la ruta /opportunities muestra un ranking FACTORIAL (momentum/calidad/valor/crecimiento)
// que NO pasa por la política de valoración gobernante (motor v2) ni por su barrera metodológica. Por eso
// NUNCA debe presentarse como recomendación accionable. Este módulo fija esa regla de forma testable:
//  - El scan factorial es una señal INDEPENDIENTE e informativa; por sí solo nunca es accionable.
//  - Mientras la metodología de Fair Value no esté validada por backtest, se refuerza el aviso de bloqueo.
export interface OpportunityDisclosure {
  actionable: boolean;        // el scan factorial NUNCA es accionable por sí mismo
  blocked: boolean;           // además, la metodología gobernante está bloqueada
  tone: "warn" | "muted";
  banner: string;
}

export function opportunityDisclosure(methodologyValidated: boolean): OpportunityDisclosure {
  if (!methodologyValidated) {
    return {
      actionable: false, blocked: true, tone: "warn",
      banner: "Señales factoriales informativas — NO son recomendaciones de compra. La valoración gobernante " +
              "(motor v2) tiene su metodología bloqueada (no validada por backtest): no hay recomendaciones " +
              "accionables en ninguna pantalla.",
    };
  }
  return {
    actionable: false, blocked: false, tone: "muted",
    banner: "Señales factoriales de atractivo relativo — informativas; no sustituyen ni habilitan por sí solas " +
            "la valoración gobernante del Asesor.",
  };
}
