// P2.4 — POLÍTICA DE VALORACIÓN ÚNICA (consumida por Scanner y Advisor 3.0; sin duplicar criterios).
// Gobierna qué modelo manda por instrumento y con qué confianza:
//   - El FV PRODUCTIVO es PRIMARIO cuando existe y es comparable (nunca lo desplaza el FCFF).
//   - El FCFF experimental solo GOBIERNA como FALLBACK cuando (a) no hay FV productivo, (b) el flag
//     de fallback está habilitado y (c) su confianza supera los controles. Si el flag está apagado,
//     el FCFF es solo CONTEXTO (no gobierna) — comportamiento histórico, reversible.
//   - Datos insuficientes → sin valoración (no se inventa Fair Value).
// Tiers: calculado (corre) / confiable (productivo) / experimental (FCFF fallback) / insuficiente.
export type Conf = "alta" | "media" | "baja" | null;
export type GovSource = "motor_v2" | "productivo" | "fcff_fallback" | "fcff(contexto)" | "ninguno";
export type ValTier = "confiable" | "experimental" | "insuficiente";

export interface GovInput {
  // MOTOR v2 (FCFF DCF data-driven reconciliado) — FV ÚNICO GOBERNANTE con estado de validación.
  // Cuando existe, MANDA sobre todo lo demás. Accionable SOLO si engineStatus === "consistente"
  // (consistencia ARITMÉTICA; no implica validación económica/predictiva).
  // "en_revision"/"no_valorable" ⇒ FV visible pero BLOQUEADO (no genera compras/asignaciones).
  engineMargin?: number | null; engineStatus?: "consistente" | "en_revision" | "no_valorable" | null;
  engineConfidence?: Conf; engineReason?: string | null;
  // BARRERA DE METODOLOGÍA (item 7): accionable SOLO si además la metodología está validada por backtest.
  // Ausente o false ⇒ el FV es visible e informativo pero NO accionable (no genera compras), aunque sea
  // "consistente" aritméticamente. Hoy el backend la envía en false (backtest pendiente).
  engineMethodologyValidated?: boolean;
  productiveMargin: number | null; productiveConfidence: Conf;
  fcffMargin?: number | null; fcffConfidence?: Conf;
  priceComparable?: boolean;
  // BARRERA DE SEGURIDAD (diagnóstico PFE): el backend marca una valoración FCFF data-driven con
  // inconsistencia económica no resuelta (reinversión neta negativa persistente con crecimiento
  // positivo = "crecimiento gratis", o ADR/divisa/acciones sin resolver). No cambia el Fair Value;
  // solo IMPIDE que esa valoración genere compras/asignaciones hasta corregir el motor.
  reviewBlock?: boolean; reviewReason?: string | null;
}
export interface GovResult {
  margin: number | null; conf: Conf; source: GovSource; tier: ValTier; note: string;
  blocked?: boolean; blockReason?: string | null;   // en revisión: no accionable (FV intacto)
}
// methodologyValidated: barrera GLOBAL (item 7). Si es === false, NINGUNA fuente (motor_v2, productivo o
// FCFF) es accionable: todas las valoraciones dependen de una metodología aún no validada por backtest.
// Ausente ⇒ no se aplica la barrera global (compatibilidad). El data layer la envía en false hoy.
export interface PolicyOpts { fcffFallback?: boolean; methodologyValidated?: boolean }

// Margen implausible (FV muy lejos del precio) ⇒ modelo frágil: la confianza se degrada a 'baja' para
// que no respalde una asignación, aunque la fila guardada diga otra cosa (control de calidad P2.4.1).
export const EXTREME_MARGIN = 0.80;

export function sufficient(c: Conf): boolean { return c === "alta" || c === "media"; }

// Degrada a confianza baja/experimental cuando el margen es extremo (salvaguarda de lectura).
function guardExtreme(r: GovResult): GovResult {
  if (r.margin != null && Math.abs(r.margin) >= EXTREME_MARGIN) {
    return { ...r, conf: "baja", tier: "experimental", note: `${r.note} | margen extremo (${(r.margin * 100).toFixed(0)}%): confianza degradada, no apto para asignación` };
  }
  return r;
}

export function governingValuation(v: GovInput | undefined, opts?: PolicyOpts): GovResult {
  const fallback = !!opts?.fcffFallback;
  // Barrera GLOBAL de metodología (item 7): si está explícitamente no validada, cualquier fuente que
  // gobierne queda BLOQUEADA (FV visible e informativo, no accionable). Reversible al validar por backtest.
  const methodBlocked = opts?.methodologyValidated === false;
  const mReason = "metodología no validada (backtest pendiente) — FV informativo, no accionable";
  if (!v) return { margin: null, conf: null, source: "ninguno", tier: "insuficiente", note: "sin valoración" };
  // 0) MOTOR v2 — FV ÚNICO GOBERNANTE. Si existe, manda. Accionable solo si validado; en revisión o no
  //    valorable ⇒ FV visible pero bloqueado (no accionable). Reemplaza la jerarquía productivo/FCFF.
  if (v.engineMargin != null && v.engineStatus) {
    const arithmeticOk = v.engineStatus === "consistente";
    const methodOk = v.engineMethodologyValidated ?? false;      // metodología validada por backtest
    const actionable = arithmeticOk && methodOk;                 // accionable SOLO con ambas
    const blk = !actionable;
    const reason = !arithmeticOk
      ? (v.engineReason ?? (v.engineStatus === "no_valorable"
          ? "no valorable (datos no reconstruibles)" : "en revisión (control financiero no superado)"))
      : "metodología no validada (backtest pendiente) — FV informativo, no accionable";
    return guardExtreme({
      margin: v.engineMargin, conf: v.engineConfidence ?? (arithmeticOk ? "media" : "baja"),
      source: "motor_v2" as GovSource, tier: actionable ? "confiable" : "experimental",
      note: actionable
        ? "Motor v2 (FCFF DCF reconciliado) — consistente y metodología validada"
        : arithmeticOk
          ? "Motor v2 — consistente aritméticamente; metodología no validada (no accionable)"
          : `Motor v2 — ${reason}`,
      blocked: blk, blockReason: blk ? reason : null,
    });
  }
  // 1) FV productivo primario (el FCFF, si existe y es suficiente, solo corrobora)
  if (v.productiveMargin != null && v.priceComparable !== false) {
    const corro = v.fcffMargin != null && sufficient(v.fcffConfidence ?? null)
      ? ` (FCFF ${v.fcffMargin >= 0 ? "+" : ""}${(v.fcffMargin * 100).toFixed(0)}% corrobora)` : "";
    return guardExtreme({ margin: v.productiveMargin, conf: v.productiveConfidence, source: "productivo",
      tier: methodBlocked ? "experimental" : "confiable",
      note: methodBlocked ? `FV productivo — ${mReason}` : `FV productivo${corro}`,
      blocked: methodBlocked, blockReason: methodBlocked ? mReason : null });
  }
  // 2) sin FV productivo: FCFF como FALLBACK (solo si flag + confianza suficiente) o CONTEXTO.
  //    BARRERA: si la valoración está marcada en revisión, o la metodología no está validada, se bloquea.
  const blk = !!v.reviewBlock || methodBlocked;
  const blkR = methodBlocked ? mReason : (v.reviewReason ?? "valoración en revisión (inconsistencia económica no resuelta)");
  if (v.fcffMargin != null && sufficient(v.fcffConfidence ?? null)) {
    if (fallback) return guardExtreme({ margin: v.fcffMargin, conf: v.fcffConfidence ?? null, source: "fcff_fallback", tier: "experimental", note: blk ? `sin FV productivo; FCFF BLOQUEADO: ${blkR}` : "sin FV productivo; FCFF como fallback bajo controles (experimental)", blocked: blk, blockReason: blk ? blkR : null });
    return { margin: v.fcffMargin, conf: "baja", source: "fcff(contexto)", tier: "experimental", note: "sin FV productivo; FCFF solo como contexto (no gobierna; fallback apagado)", blocked: blk, blockReason: blk ? blkR : null };
  }
  // 3) nada utilizable → no se inventa FV
  return { margin: null, conf: null, source: "ninguno", tier: "insuficiente", note: "sin FV productivo; FCFF insuficiente" };
}

// Criba de VALOR: solo gobierna la compra un margen suficiente con confianza suficiente de una fuente
// que manda (productivo, o FCFF fallback bajo controles). Un margen positivo por sí solo NO basta.
export function passesValueGate(v: GovInput | undefined, minMargin: number, opts?: PolicyOpts): boolean {
  const g = governingValuation(v, opts);
  return !g.blocked && g.margin != null && g.margin >= minMargin && sufficient(g.conf)
    && (g.source === "motor_v2" || g.source === "productivo" || g.source === "fcff_fallback");
}

// ¿La valoración que gobernaría está EN REVISIÓN (barrera activa)? Para que la UI lo muestre.
export function underReview(v: GovInput | undefined, opts?: PolicyOpts): { blocked: boolean; reason: string | null } {
  const g = governingValuation(v, opts);
  return { blocked: !!g.blocked, reason: g.blockReason ?? null };
}
