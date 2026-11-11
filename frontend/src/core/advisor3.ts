// P2.1 — Advisor 3.0 (EXPERIMENTAL, bajo feature flag). Motor PURO y testeable. Combina:
//  A) valoración fundamental + margen de seguridad, B) confianza/sensibilidad, C) calidad financiera,
//  D) riesgo y concentración de cartera, E) liquidez y aportes nuevos, F) costo de oportunidad.
// Mantiene SEPARADAS: decisiones sobre posiciones (MANTENER/REDUCIR/VENDER/REVISAR) y asignación de
// capital nuevo (COMPRAR/ACUMULAR/ESPERAR). NUNCA convierte un margen positivo en compra automática:
// exige confianza suficiente + chequeos de riesgo/concentración. El FCFF experimental de baja
// confianza NO desplaza el Fair Value productivo. No ejecuta operaciones.
import { riskContributions, concentration, fxExposure, type RiskContrib } from "./portfolio-risk";

export type PositionAction = "MANTENER" | "REDUCIR" | "VENDER" | "REVISAR";
export type ContribAction = "COMPRAR" | "ACUMULAR" | "ESPERAR";
export type Conf = "alta" | "media" | "baja" | null;

export interface Adv3Position {
  ticker: string; name?: string | null; sector?: string | null; country?: string | null;
  currency?: string | null; assetClass?: string | null; marketValue: number; weight: number;
}
export interface Adv3Valuation {
  // Fair Value PRODUCTIVO (referencia que manda) + FCFF experimental (contexto, no desplaza).
  productiveMargin: number | null; productiveConfidence: Conf;
  fcffMargin?: number | null; fcffConfidence?: Conf;
  priceComparable?: boolean;
}
export interface Adv3Quality { eligible: boolean; fresh: boolean }
export interface Adv3Constraints { maxPositionWeight: number; maxSectorWeight: number; minMarginToBuy?: number }
export interface Adv3Input {
  positions: Adv3Position[];
  cash: number;
  contribution: number;                       // aporte nuevo configurable (p.ej. 3000 USD)
  returns: Record<string, number[]>;          // retornos alineados (riesgo)
  valuation: Record<string, Adv3Valuation>;
  quality: Record<string, Adv3Quality>;
  etfLookthrough?: Record<string, Record<string, number>>;
  constraints: Adv3Constraints;
}

export interface Explain {
  motivos: string[]; datosModelos: string[]; riesgos: string[];
  factores: string[];   // cuáles de los 5 factores impulsaron la decisión (valoración, concentración, riesgo, deterioro, confianza/desacuerdo)
  impactoCartera: Record<string, number | string>; condicionesCambio: string[];
}
export interface PositionDecision {
  ticker: string; action: PositionAction; confidence: Conf;
  marginUsed: number | null; marginSource: "productivo" | "fcff(contexto)" | "ninguno";
  riskContribPct: number; explain: Explain;
}
export interface AllocItem { ticker: string; amount: number; newWeight: number; action: ContribAction; reason: string }
export interface AllocOption {
  id: string; label: string; items: AllocItem[]; cashKept: number;
  volAfter: number; hhiSectorAfter: number; score: number; preferred: boolean; why: string;
}
export interface Advisor3Report {
  asOf: string;
  portfolioValue: number; cash: number;
  risk: { volAnnual: number; topContributors: { ticker: string; pct: number }[];
          hhiSector: number; hhiCountry: number; fxNonBase: number };
  positionDecisions: PositionDecision[];
  allocation: { contribution: number; options: AllocOption[]; chosen: string; note: string };
  guardrails: string[];
  dataUsed: string[];
}

const STUB_W = 0.015;
const UNDER = 0.10, STRONG_OVER = -0.25, OVER = -0.10;
const RISK_TRIM = 0.30;        // contribución al riesgo que justifica RECORTAR (nunca vender por sí sola)
const DISAGREE_MAG = 0.25;     // brecha de margen productivo vs FCFF que se considera desacuerdo material
const DIVERSIFY_MIN = 0.002;   // reducción mínima de HHI sector para que un ETF cuente como diversificación real

// Umbrales auditables, reutilizables por el Opportunity Scanner (P2.2) sin duplicar criterios.
export const ADV3_THRESHOLDS = { STUB_W, UNDER, OVER, STRONG_OVER, RISK_TRIM, DISAGREE_MAG, DIVERSIFY_MIN } as const;

export function sufficient(c: Conf): boolean { return c === "alta" || c === "media"; }

// Desacuerdo entre el DCF productivo y el FCFF experimental. No ignora la discrepancia: la clasifica.
export function modelDisagreement(v: Adv3Valuation | undefined): { material: boolean; kind: "direccional" | "magnitud" | null; gap: number | null } {
  if (!v || v.productiveMargin == null || v.fcffMargin == null) return { material: false, kind: null, gap: null };
  const p = v.productiveMargin, f = v.fcffMargin, gap = Math.abs(p - f);
  const opposite = (p > UNDER && f < -UNDER) || (p < -UNDER && f > UNDER);  // lados claramente opuestos
  if (opposite) return { material: true, kind: "direccional", gap };
  if (gap >= DISAGREE_MAG) return { material: true, kind: "magnitud", gap };
  return { material: false, kind: null, gap };
}

// Valoración efectiva: manda el FV PRODUCTIVO; el FCFF solo corrobora/contextualiza y NO lo desplaza.
export function effectiveMargin(v: Adv3Valuation | undefined): { margin: number | null; conf: Conf; source: PositionDecision["marginSource"]; note: string } {
  if (!v) return { margin: null, conf: null, source: "ninguno", note: "sin valoración" };
  if (v.productiveMargin != null && v.priceComparable !== false) {
    const corro = v.fcffMargin != null && sufficient(v.fcffConfidence ?? null)
      ? ` (FCFF ${v.fcffMargin >= 0 ? "+" : ""}${(v.fcffMargin * 100).toFixed(0)}% corrobora)` : "";
    return { margin: v.productiveMargin, conf: v.productiveConfidence, source: "productivo", note: `FV productivo${corro}` };
  }
  // sin FV productivo comparable: el FCFF experimental es SOLO contexto, nunca manda si su confianza es baja
  if (v.fcffMargin != null && sufficient(v.fcffConfidence ?? null)) {
    return { margin: v.fcffMargin, conf: "baja", source: "fcff(contexto)", note: "sin FV productivo; FCFF experimental como contexto (confianza degradada)" };
  }
  return { margin: null, conf: null, source: "ninguno", note: "sin FV productivo comparable; FCFF insuficiente" };
}

export function isEtf(a?: string | null) { return ["etf", "fund", "etn", "mutualfund"].includes((a ?? "").toLowerCase()); }

// Criba de valor REUTILIZABLE: solo el FV PRODUCTIVO con margen suficiente y confianza suficiente
// habilita compra. El FCFF experimental de baja confianza NO habilita. Un margen positivo por sí
// solo NO basta. La usan tanto la asignación de Advisor 3.0 como el Opportunity Scanner (sin duplicar).
export function passesValueGate(v: Adv3Valuation | undefined, minMargin: number): boolean {
  const em = effectiveMargin(v);
  return em.margin != null && em.margin >= minMargin && sufficient(em.conf) && em.source === "productivo";
}

export function buildAdvisor3(inp: Adv3Input, asOf = new Date().toISOString().slice(0, 10)): Advisor3Report {
  const { positions, cash, contribution, returns, valuation, quality, constraints } = inp;
  const totalInvested = positions.reduce((s, p) => s + p.marketValue, 0);
  const portfolioValue = totalInvested + cash;
  const weights: Record<string, number> = {};
  for (const p of positions) weights[p.ticker] = portfolioValue > 0 ? p.marketValue / portfolioValue : 0;

  const rc: RiskContrib = riskContributions(weights, returns);
  const meta: Record<string, { sector?: string; country?: string; currency?: string }> = {};
  for (const p of positions) meta[p.ticker] = { sector: p.sector ?? "na", country: p.country ?? "na", currency: p.currency ?? "USD" };
  const concSector = concentration(weights, meta, "sector");
  const concCountry = concentration(weights, meta, "country");
  const fx = fxExposure(weights, meta, "USD");
  const topContribs = Object.entries(rc.byPosition).map(([t, c]) => ({ ticker: t, pct: c.contribPct }))
    .sort((a, b) => b.pct - a.pct).slice(0, 3);

  // ---------- A) decisiones sobre posiciones existentes ----------
  const positionDecisions: PositionDecision[] = positions.map((p) => {
    const em = effectiveMargin(valuation[p.ticker]);
    const dis = modelDisagreement(valuation[p.ticker]);
    const q = quality[p.ticker];
    const contribPct = rc.byPosition[p.ticker]?.contribPct ?? 0;
    const topRisk = contribPct > RISK_TRIM;                    // contribuye > umbral del riesgo total
    const sectorW = concSector.byGroup[p.sector ?? "na"] ?? 0;
    const overSector = sectorW > constraints.maxSectorWeight;
    const deterioro = !!q && (!q.eligible || !q.fresh);        // deterioro de fundamentales (datos)
    const corrobora = (em.margin != null && (valuation[p.ticker]?.fcffMargin ?? 1) <= 0) || deterioro;
    const motivos: string[] = []; const riesgos: string[] = []; const cond: string[] = []; const factores: string[] = [];
    let action: PositionAction;

    if (p.weight < STUB_W) {
      action = "REVISAR"; factores.push("tamaño");
      motivos.push(`Posición ínfima (${(p.weight * 100).toFixed(1)}%): tamaño inmaterial → revisar; vender exige razón económica, no solo tamaño.`);
    } else if (isEtf(p.assetClass)) {
      action = overSector ? "REVISAR" : "MANTENER"; factores.push("vehículo");
      motivos.push(overSector ? "Vehículo que agrava concentración sectorial → revisar." : "Vehículo diversificado dentro de límites: cumple su rol (se evalúa por cartera, no por DCF).");
    } else if (em.margin == null) {
      action = "REVISAR"; factores.push("sin-valoración");
      motivos.push(`Sin valoración concluyente (${em.note}).`);
      cond.push("Disponer de FV productivo comparable o consenso validado elevaría la conclusión.");
    } else if (dis.kind === "direccional") {
      action = "REVISAR"; factores.push("desacuerdo-modelos");
      motivos.push(`Desacuerdo DIRECCIONAL entre DCF productivo (${(em.margin * 100).toFixed(0)}%) y FCFF (${((valuation[p.ticker]!.fcffMargin!) * 100).toFixed(0)}%): no se concluye por valoración.`);
      cond.push("Convergencia de modelos (o consenso validado) permitiría concluir.");
    } else if (em.margin <= STRONG_OVER && sufficient(em.conf) && corrobora && !dis.material) {
      // VENDER: criterio EXIGENTE — sobrevaloración fuerte + confianza + corroboración (FCFF mismo lado
      // o deterioro) + SIN desacuerdo material. La concentración NO es un criterio de venta.
      action = "VENDER"; factores.push("sobrevaloración-fuerte", "confianza", deterioro ? "deterioro" : "corroboración-FCFF");
      motivos.push(`Muy sobrevalorada (margen ${(em.margin * 100).toFixed(0)}%, ${em.note}, confianza ${em.conf})${deterioro ? " + deterioro de fundamentales" : " corroborada por FCFF"}.`);
    } else if (em.margin <= STRONG_OVER && sufficient(em.conf) && dis.kind === "magnitud") {
      action = "REDUCIR"; factores.push("sobrevaloración-fuerte", "desacuerdo-magnitud");
      motivos.push(`Muy sobrevalorada por el FV productivo (${(em.margin * 100).toFixed(0)}%) PERO desacuerdo de magnitud con el FCFF (brecha ${((dis.gap ?? 0) * 100).toFixed(0)} pp): se ATENÚA de VENDER a REDUCIR por incertidumbre.`);
    } else if (em.margin <= STRONG_OVER && !sufficient(em.conf)) {
      action = "REDUCIR"; factores.push("sobrevaloración-fuerte", "confianza-insuficiente");
      motivos.push(`Muy sobrevalorada (${(em.margin * 100).toFixed(0)}%) pero confianza insuficiente: REDUCIR, no VENDER.`);
    } else if (em.margin <= OVER && sufficient(em.conf)) {
      action = "REDUCIR"; factores.push("sobrevaloración-moderada");
      motivos.push(`Sobrevalorada moderada (margen ${(em.margin * 100).toFixed(0)}%, confianza ${em.conf}).`);
    } else if ((topRisk || overSector) && em.margin < UNDER) {
      // RIESGO: recortar por concentración/contribución, NUNCA vender por esto solo.
      action = "REDUCIR"; factores.push("riesgo/concentración");
      motivos.push(`Valoración no barata; top contribuyente de riesgo (${(contribPct * 100).toFixed(0)}%)${overSector ? ` y sector sobre el límite (${(sectorW * 100).toFixed(0)}%)` : ""}: RECORTAR por riesgo, no vender.`);
    } else {
      action = "MANTENER"; factores.push("en-límites");
      motivos.push(em.margin >= UNDER ? `Dentro de límites y con margen (${(em.margin * 100).toFixed(0)}%, confianza ${em.conf}).` : `Valorada en rango razonable y dentro de límites de riesgo.`);
    }
    if (dis.material && action !== "REVISAR") riesgos.push(`Desacuerdo de modelos (${dis.kind}, brecha ${((dis.gap ?? 0) * 100).toFixed(0)} pp): confianza de la acción degradada.`);
    if (q && !q.eligible) riesgos.push("Calidad/elegibilidad financiera degradada (datos incompletos).");
    if (q && !q.fresh) riesgos.push("Fundamentales no recientes.");
    if (topRisk) riesgos.push(`Concentración de riesgo: ${(contribPct * 100).toFixed(0)}% del riesgo del portafolio (criterio de REDUCIR, no de VENDER).`);
    cond.push(action === "MANTENER" ? "Un deterioro de margen (<-10%) con confianza suficiente movería a REDUCIR." : action === "VENDER" ? "Una convergencia al alza del FV o menor sobrevaloración movería a REDUCIR/MANTENER." : "Una mejora de margen con confianza suficiente, o convergencia de modelos, movería a MANTENER.");
    return {
      ticker: p.ticker, action, confidence: em.conf, marginUsed: em.margin, marginSource: em.source,
      riskContribPct: Number(contribPct.toFixed(4)),
      explain: {
        motivos, datosModelos: [`valoración: ${em.source}`, "riesgo: contribución por Euler (retornos históricos)", "concentración: HHI sector/país"],
        riesgos, factores,
        impactoCartera: { peso: Number(p.weight.toFixed(4)), contrib_riesgo_pct: Number(contribPct.toFixed(4)) },
        condicionesCambio: cond,
      },
    };
  });

  // ---------- B) asignación de capital nuevo (configurable) ----------
  const minMargin = constraints.minMarginToBuy ?? UNDER;
  // candidatos a desplegar: margen >= umbral con confianza suficiente, sin romper límites de peso.
  // Solo FV PRODUCTIVO habilita compra (el FCFF de baja confianza NO).
  const candidates = positions.filter((p) =>
    !isEtf(p.assetClass) && passesValueGate(valuation[p.ticker], minMargin) && p.weight < constraints.maxPositionWeight);

  function optionFrom(id: string, label: string, dist: { ticker: string; amount: number }[], reasonBy: Record<string, string>): AllocOption {
    // redondea importes primero; conservación de capital EXACTA: efectivo = aporte − Σ(redondeados)
    const rounded = dist.map((d) => ({ ticker: d.ticker, amount: Math.round(d.amount) })).filter((d) => d.amount > 0);
    const deployed = rounded.reduce((s, d) => s + d.amount, 0);
    const cashKept = contribution - deployed;
    const newTotal = portfolioValue + deployed;
    const amtOf = (tk: string) => rounded.find((d) => d.ticker === tk)?.amount ?? 0;
    const nw: Record<string, number> = {};
    for (const p of positions) nw[p.ticker] = (p.marketValue + amtOf(p.ticker)) / newTotal;
    const after = riskContributions(nw, returns);
    const hhiA = concentration(nw, meta, "sector").hhi;
    const valueScore = rounded.reduce((s, d) => { const em = effectiveMargin(valuation[d.ticker]); return s + (em.margin ?? 0) * d.amount; }, 0) / (contribution || 1);
    const concPenalty = Math.max(0, hhiA - concSector.hhi) * 5;
    const score = Number((valueScore - concPenalty).toFixed(4));
    const items: AllocItem[] = rounded.map((d) => ({
      ticker: d.ticker, amount: d.amount, newWeight: Number(nw[d.ticker].toFixed(4)),
      action: (positions.find((p) => p.ticker === d.ticker)?.marketValue ?? 0) > 0 ? "ACUMULAR" : "COMPRAR",
      reason: reasonBy[d.ticker] ?? "",
    }));
    return { id, label, items, cashKept, volAfter: Number(after.volPortfolioAnnual.toFixed(4)), hhiSectorAfter: Number(hhiA.toFixed(4)), score, preferred: false, why: "" };
  }

  const options: AllocOption[] = [];
  // Opción 0: todo en efectivo (ESPERAR) — baseline siempre disponible
  options.push({ id: "efectivo", label: "Mantener en efectivo", items: [], cashKept: Math.round(contribution),
    volAfter: Number(rc.volPortfolioAnnual.toFixed(4)), hhiSectorAfter: Number(concSector.hhi.toFixed(4)), score: 0, preferred: false,
    why: "Sin oportunidades que superen el umbral de margen+confianza+riesgo, o por disciplina de liquidez." });

  if (candidates.length) {
    const emOf = (p: Adv3Position) => effectiveMargin(valuation[p.ticker]);
    const roomValue = (p: Adv3Position) => Math.max(0, constraints.maxPositionWeight * (portfolioValue + contribution) - p.marketValue);
    // Opción 1: VALOR — concentra en el mejor margen con confianza, respetando tope de peso
    const best = [...candidates].sort((a, b) => (emOf(b).margin ?? 0) - (emOf(a).margin ?? 0));
    const distV: { ticker: string; amount: number }[] = []; let rem = contribution;
    for (const p of best) { if (rem <= 0) break; const amt = Math.min(rem, roomValue(p)); if (amt > 0) { distV.push({ ticker: p.ticker, amount: amt }); rem -= amt; } }
    options.push(optionFrom("valor", "Desplegar en valor (mejor margen con confianza)", distV,
      Object.fromEntries(best.map((p) => { const em = emOf(p); return [p.ticker, `margen ${((em.margin ?? 0) * 100).toFixed(0)}% confianza ${em.conf}`]; }))));

    // Opción 2: DIVERSIFICAR (acciones) — reparte equitativo entre candidatos para no agravar concentración
    const share = contribution / candidates.length;
    const distD = candidates.map((p) => ({ ticker: p.ticker, amount: Math.min(share, roomValue(p)) }));
    options.push(optionFrom("diversificar", "Desplegar diversificando entre candidatos", distD,
      Object.fromEntries(candidates.map((p) => [p.ticker, "reparto para limitar concentración"]))));
  }

  // Opción ETF DIVERSIFICADOR — comprar un ETF YA en cartera para REDUCIR concentración (HHI sector),
  // justificado por diversificación medible, NO por margen ni retornos inventados. Solo si hay ETF en cartera.
  const heldEtfs = positions.filter((p) => isEtf(p.assetClass) && p.marketValue > 0);
  let etfHhiReduction = 0;
  if (heldEtfs.length) {
    const share = contribution / heldEtfs.length;
    const distE = heldEtfs.map((p) => ({ ticker: p.ticker, amount: share }));
    const optE = optionFrom("etf", "Diversificar vía ETF en cartera (reduce concentración, no por margen)", distE,
      Object.fromEntries(heldEtfs.map((p) => [p.ticker, "aumenta diversificación; se evalúa por cartera, no por DCF"])));
    etfHhiReduction = concSector.hhi - optE.hhiSectorAfter;    // >0 si el aporte reduce la concentración sectorial
    optE.score = Number(Math.max(0, etfHhiReduction).toFixed(4));  // crédito de diversificación, escala propia (HHI)
    options.push(optE);
  }

  // Problema de concentración real: un top-contribuyente > umbral o un sector por encima del límite.
  const hasConcProblem = topContribs.some((c) => c.pct > RISK_TRIM)
    || Object.values(concSector.byGroup).some((w) => w > constraints.maxSectorWeight);

  // Jerarquía TRANSPARENTE (sin comparar escalas distintas como si fueran iguales):
  //  1) si hay acciones con margen+confianza (candidatos) y aportan valor neto → desplegar en valor/diversificar;
  //  2) si NO, pero hay problema de concentración y un ETF lo reduce de forma material → ETF diversificador;
  //  3) si nada supera los criterios → ESPERAR (efectivo). ESPERAR es una decisión válida, no un fallo.
  let chosen = "efectivo";
  const equityDeployables = options.filter((o) => (o.id === "valor" || o.id === "diversificar") && o.items.length);
  if (equityDeployables.length) {
    const top = equityDeployables.sort((a, b) => b.score - a.score)[0];
    if (top.score > 0) chosen = top.id;      // score>0 = aporta valor neto de penalización por concentración
  }
  if (chosen === "efectivo" && hasConcProblem && etfHhiReduction >= DIVERSIFY_MIN) {
    chosen = "etf";                           // sin oportunidades de valor, pero reducir concentración sí es acción
  }
  options.forEach((o) => { o.preferred = o.id === chosen; });
  const chosenOpt = options.find((o) => o.id === chosen)!;
  chosenOpt.why = chosen === "efectivo"
    ? (hasConcProblem
        ? "Hay concentración elevada, pero ningún despliegue (acción con margen+confianza ni ETF con reducción material de HHI) supera el umbral; se ESPERA sin forzar la inversión."
        : "Ninguna alternativa supera el umbral de valor/riesgo y no hay problema de concentración que resolver; se ESPERA (ESPERAR es válido).")
    : chosen === "etf"
    ? `Sin acciones que superen margen+confianza, pero la cartera está concentrada y este ETF reduce el HHI sector en ${(etfHhiReduction).toFixed(4)}: se diversifica por RIESGO, no por margen.`
    : `Mejor score de valor neto de concentración (${chosenOpt.score}); respeta topes de peso y mantiene el riesgo controlado.`;

  const guardrails = [
    "El FCFF experimental de baja confianza NO desplaza el Fair Value productivo; solo corrobora/contextualiza.",
    "Un margen de seguridad positivo NO basta para COMPRAR: exige confianza suficiente y chequeos de riesgo/concentración.",
    "Dos decisiones separadas: posición existente vs asignación de capital nuevo.",
    "No ejecuta operaciones ni modifica inversiones reales.",
  ];
  return {
    asOf, portfolioValue, cash,
    risk: { volAnnual: Number(rc.volPortfolioAnnual.toFixed(4)), topContributors: topContribs.map((c) => ({ ticker: c.ticker, pct: Number(c.pct.toFixed(4)) })),
            hhiSector: Number(concSector.hhi.toFixed(4)), hhiCountry: Number(concCountry.hhi.toFixed(4)), fxNonBase: Number(fx.nonBase.toFixed(4)) },
    positionDecisions,
    allocation: { contribution, options, chosen, note: chosenOpt.why },
    guardrails,
    dataUsed: ["posiciones reales (derivePositions)", "retornos históricos (price_history)", "FV productivo + FCFF experimental (P1.9)", "calidad/elegibilidad (fundamentals_pit)", "riesgo (portfolio-risk, paridad Python)"],
  };
}
