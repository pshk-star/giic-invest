// P2.4 — POLÍTICA DE VALORACIÓN ÚNICA (consumida por Scanner y Advisor 3.0; sin duplicar criterios).
// Gobierna qué modelo manda por instrumento y con qué confianza:
//   - El FV PRODUCTIVO es PRIMARIO cuando existe y es comparable (nunca lo desplaza el FCFF).
//   - El FCFF experimental solo GOBIERNA como FALLBACK cuando (a) no hay FV productivo, (b) el flag
//     de fallback está habilitado y (c) su confianza supera los controles. Si el flag está apagado,
//     el FCFF es solo CONTEXTO (no gobierna) — comportamiento histórico, reversible.
//   - Datos insuficientes → sin valoración (no se inventa Fair Value).
// Tiers: calculado (corre) / confiable (productivo) / experimental (FCFF fallback) / insuficiente.
export type Conf = "alta" | "media" | "baja" | null;
export type GovSource = "productivo" | "fcff_fallback" | "fcff(contexto)" | "ninguno";
export type ValTier = "confiable" | "experimental" | "insuficiente";

export interface GovInput {
  productiveMargin: number | null; productiveConfidence: Conf;
  fcffMargin?: number | null; fcffConfidence?: Conf;
  priceComparable?: boolean;
}
export interface GovResult {
  margin: number | null; conf: Conf; source: GovSource; tier: ValTier; note: string;
}
export interface PolicyOpts { fcffFallback?: boolean }

export function sufficient(c: Conf): boolean { return c === "alta" || c === "media"; }

export function governingValuation(v: GovInput | undefined, opts?: PolicyOpts): GovResult {
  const fallback = !!opts?.fcffFallback;
  if (!v) return { margin: null, conf: null, source: "ninguno", tier: "insuficiente", note: "sin valoración" };
  // 1) FV productivo primario (el FCFF, si existe y es suficiente, solo corrobora)
  if (v.productiveMargin != null && v.priceComparable !== false) {
    const corro = v.fcffMargin != null && sufficient(v.fcffConfidence ?? null)
      ? ` (FCFF ${v.fcffMargin >= 0 ? "+" : ""}${(v.fcffMargin * 100).toFixed(0)}% corrobora)` : "";
    return { margin: v.productiveMargin, conf: v.productiveConfidence, source: "productivo", tier: "confiable", note: `FV productivo${corro}` };
  }
  // 2) sin FV productivo: FCFF como FALLBACK (solo si flag + confianza suficiente) o CONTEXTO
  if (v.fcffMargin != null && sufficient(v.fcffConfidence ?? null)) {
    if (fallback) return { margin: v.fcffMargin, conf: v.fcffConfidence ?? null, source: "fcff_fallback", tier: "experimental", note: "sin FV productivo; FCFF como fallback bajo controles (experimental)" };
    return { margin: v.fcffMargin, conf: "baja", source: "fcff(contexto)", tier: "experimental", note: "sin FV productivo; FCFF solo como contexto (no gobierna; fallback apagado)" };
  }
  // 3) nada utilizable → no se inventa FV
  return { margin: null, conf: null, source: "ninguno", tier: "insuficiente", note: "sin FV productivo; FCFF insuficiente" };
}

// Criba de VALOR: solo gobierna la compra un margen suficiente con confianza suficiente de una fuente
// que manda (productivo, o FCFF fallback bajo controles). Un margen positivo por sí solo NO basta.
export function passesValueGate(v: GovInput | undefined, minMargin: number, opts?: PolicyOpts): boolean {
  const g = governingValuation(v, opts);
  return g.margin != null && g.margin >= minMargin && sufficient(g.conf)
    && (g.source === "productivo" || g.source === "fcff_fallback");
}
