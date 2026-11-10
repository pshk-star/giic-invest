/// <reference types="vite/client" />

interface ImportMetaEnv {
  // P1.9 — feature flag reversible de la vista de valoración fundamental (experimental).
  readonly VITE_FF_FUNDVAL?: string;
  // P2.1 — feature flag reversible de Advisor 3.0 (experimental).
  readonly VITE_FF_ADVISOR3?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
