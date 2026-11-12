/// <reference types="vite/client" />

interface ImportMetaEnv {
  // P1.9 — feature flag reversible de la vista de valoración fundamental (experimental).
  readonly VITE_FF_FUNDVAL?: string;
  // P2.1 — feature flag reversible de Advisor 3.0 (experimental).
  readonly VITE_FF_ADVISOR3?: string;
  // P2.2 — feature flag reversible del Opportunity Scanner (experimental).
  readonly VITE_FF_SCANNER?: string;
  // P2.4 — política de valoración: habilita FCFF como fallback sin FV productivo (reversible).
  readonly VITE_FF_VALPOLICY?: string;
  // P2.5 — plan de asignación multiposición (experimental, reversible).
  readonly VITE_FF_ALLOC?: string;
  // P2.6 — historial de decisiones y resultados (experimental, reversible).
  readonly VITE_FF_DECISIONS?: string;
  // Etapa A — Investment Advisor unificado (experimental, reversible).
  readonly VITE_FF_UNIFIED?: string;
  // P3.0 — rediseño integral de experiencia (experimental, reversible).
  readonly VITE_FF_P30?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
