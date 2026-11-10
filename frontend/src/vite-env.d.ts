/// <reference types="vite/client" />

interface ImportMetaEnv {
  // P1.9 — feature flag reversible de la vista de valoración fundamental (experimental).
  readonly VITE_FF_FUNDVAL?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
