// Investment Advisor 2.2 — DOS decisiones separadas por instrumento, DETERMINÍSTICO.
//  A) Acción sobre la POSICIÓN existente: MANTENER / REDUCIR / VENDER / REVISAR.
//  B) Acción sobre el CAPITAL NUEVO (aporte): ACUMULAR / COMPRAR / ESPERAR.
// No son contradictorias: p. ej. SCHD = MANTENER (posición) + ACUMULAR (aporte).
//
// Principios:
//  - MANTENER es una conclusión FUNDAMENTADA (valorada y dentro de límites, o vehículo en su rol),
//    NO un fallback. Si faltan datos para concluir ⇒ REVISAR (incertidumbre explícita).
//  - El Fair Value es una señal importante, no una condición universal para invertir.
//  - El aporte se dimensiona por CONVICCIÓN (valoración = alta; diversificación = media), con
//    liquidez residual justificada; sin mínimo de compras ni máximo artificial de efectivo.
//  - Los modelos A/B experimentales NO se usan como señal.

import type { Holding, Constraints, RiskModel } from "./advisor";
import { hhiFrom } from "./advisor";

export type Action2 = "COMPRAR" | "ACUMULAR" | "MANTENER" | "REDUCIR" | "VENDER" | "ESPERAR";
export type PositionAction = "MANTENER" | "REDUCIR" | "VENDER" | "REVISAR";
export type ContribAction = "ACUMULAR" | "COMPRAR" | "ESPERAR";
export type ValTier = "confiable" | "preliminar" | "vehiculo" | "sin-datos";

export interface FvSummary {
  available: boolean; priceComparable: boolean;
  marginBase: number | null; marginConservative: number | null; marginOptimista: number | null;
  confidence: "Alta" | "Media" | "Baja" | null; currency: string | null; reason?: string;
}
export interface ProjSummary { ret12mP50: number; ret12mP5: number; ret12mP95: number; annVol: number; }
export interface QualSummary { fresh: boolean; asOf: string | null; }
export interface EtfRouteInput {
  ticker: string; currentValue: number; effNamesAfter: number; hhiAfter: number; techAfter: number; topSector?: string | null;
}

export interface Rec2 {
  ticker: string; name: string | null; tier: ValTier;
  positionAction: PositionAction; positionWhy: string;
  contribAction: ContribAction; contribWhy: string; contribAmount: number | null;
  favor: string[]; penalize: string[]; evidence: string[]; risks: string[]; missing: string[];
  confidence: "alta" | "media" | "baja"; marginLine: string; severity: number;
}
export interface Alloc2 {
  ticker: string; route: "A" | "B" | "C"; kind: "acumular" | "nueva" | "etf";
  amount: number; pctOfCash: number; newWeight: number; reason: string; marginLine: string;
}
export interface Opp2 {
  ticker: string; name: string | null; sector: string | null; composite: number;
  action: "COMPRAR" | "OBSERVAR" | "ESPERAR" | "INVESTIGAR"; marginLine: string; note: string; eligible: boolean;
}
export interface RouteEval {
  id: "A" | "B" | "C" | "D"; label: string; available: boolean; chosen: boolean;
  amount: number; merit: string; whyNot: string | null; detail: string[];
}
export interface Advisor2Report {
  monthSummary: string; stance: "desplegar" | "parcial" | "esperar";
  portfolioValue: number; cash: number; invested: number; cashKept: number;
  allocation: Alloc2[]; routes: RouteEval[];
  before: { effN: number; topWeight: number; topTicker: string | null };
  after: { effN: number; topWeight: number; topTicker: string | null };
  cashNote: string; recommendations: Rec2[]; opportunities: Opp2[]; warnings: string[]; rules: string[]; dataUsed: string[];
}
export interface Advisor2Input {
  holdings: Holding[];
  scan: { ticker: string; name?: string | null; sector: string | null; composite: number }[];
  cash: number; constraints: Constraints;
  fv: Record<string, FvSummary>;
  proj?: Record<string, ProjSummary>; qual?: Record<string, QualSummary>; risk?: RiskModel;
  etfRoutes?: EtfRouteInput[]; effBefore?: { effN: number; hhi: number; tech: number }; scanAsOf?: string;
}

const MARGIN_UNDER = 0.10, MARGIN_STRONG_UNDER = 0.20, MARGIN_STRONG_OVER = -0.25, MARGIN_IMPLAUSIBLE = 0.60;
const SCAN_STRONG = 65, SCAN_ATTRACTIVE = 55, SCAN_WEAK = 40, MAX_RISK = 0.45, STUB_W = 0.015, MAX_ALLOC_ITEMS = 5;
const HHI_MATERIAL = 0.002;            // mejora mínima de HHI efectivo para que un ETF "diversifique"
const DEPLOY_STRONG = 1.0;             // convicción por VALORACIÓN ⇒ despliegue completo
const DEPLOY_DIVERSIFIER = 0.5;        // convicción por DIVERSIFICACIÓN (sin valoración) ⇒ despliegue parcial

const pctS = (x: number) => `${(x * 100).toFixed(1)}%`;
const usd = (x: number) => `${Math.round(x).toLocaleString("en-US")} USD`;
const effN = (hhi: number) => (hhi > 0 ? 1 / hhi : 0);
const isEtf = (a: string | null | undefined) => ["etf", "fund", "etn", "mutualfund"].includes((a ?? "").toLowerCase());
const isCommodity = (t: string, a: string | null | undefined) =>
  ["GLD", "SLV", "IAU", "PPLT", "PALL", "SGOL", "SIVR"].includes(t.toUpperCase()) || (a ?? "").toLowerCase() === "commodity";

function marginLineOf(s: FvSummary | undefined): string {
  if (!s || !s.available) return `Fair Value no disponible${s?.reason ? ` (${s.reason})` : ""}.`;
  if (!s.priceComparable || s.marginBase == null) return `Fair Value ${s.currency ?? ""} calculado, margen vs. precio no comparable (requiere FX fechado).`;
  const m = s.marginBase;
  const bucket = m > MARGIN_IMPLAUSIBLE ? "margen implausible (posible artefacto del DCF)"
    : m >= MARGIN_STRONG_UNDER ? "muy infravalorada" : m >= MARGIN_UNDER ? "infravalorada"
    : m <= MARGIN_STRONG_OVER ? "muy sobrevalorada" : m <= -MARGIN_UNDER ? "sobrevalorada" : "en rango razonable";
  return `Margen de seguridad (base) ${m >= 0 ? "+" : ""}${pctS(m)} — ${bucket} (confianza ${s.confidence}).`;
}

function roundToBudget(raw: { ticker: string; amount: number }[], budget: number): Record<string, number> {
  const target = Math.min(Math.round(budget), Math.round(raw.reduce((a, r) => a + r.amount, 0)));
  const parts = raw.map((r) => ({ t: r.ticker, floor: Math.floor(r.amount), frac: r.amount - Math.floor(r.amount) }));
  let used = parts.reduce((a, p) => a + p.floor, 0); let rem = target - used;
  parts.sort((a, b) => b.frac - a.frac);
  for (let i = 0; i < parts.length && rem > 0; i++) { parts[i].floor += 1; rem -= 1; }
  const out: Record<string, number> = {}; for (const p of parts) out[p.t] = p.floor; return out;
}
function waterfill(rooms: Map<string, number>, cash: number): Map<string, number> {
  const alloc = new Map<string, number>(); for (const k of rooms.keys()) alloc.set(k, 0);
  let remaining = cash; let active = [...rooms.keys()].filter((k) => rooms.get(k)! > 1e-9);
  for (let g = 0; g < 200 && remaining > 1e-6 && active.length > 0; g++) {
    const share = remaining / active.length; const next: string[] = []; let progressed = false;
    for (const k of active) {
      const take = Math.min(share, rooms.get(k)! - alloc.get(k)!);
      if (take > 1e-9) { alloc.set(k, alloc.get(k)! + take); remaining -= take; progressed = true; }
      if (rooms.get(k)! - alloc.get(k)! > 1e-6) next.push(k);
    }
    active = next; if (!progressed) break;
  }
  return alloc;
}

export function buildAdvice2(inp: Advisor2Input): Advisor2Report {
  const { holdings, scan, cash, constraints, fv, proj, qual, risk, etfRoutes, effBefore, scanAsOf } = inp;
  const scanBy = new Map(scan.map((s) => [s.ticker.toUpperCase(), s]));
  const held = new Set(holdings.map((h) => h.ticker.toUpperCase()));
  const V = holdings.reduce((a, h) => a + (h.marketValue ?? 0), 0);
  const cashInt = Math.max(0, Math.round(cash));
  const riskBy = new Map((risk?.contrib ?? []).map((c) => [c.ticker.toUpperCase(), c.riskPct]));
  const denom = V + cashInt; const capPerAsset = constraints.maxWeightAsset * denom;

  // ─────────── Paso 1: ACCIÓN SOBRE LA POSICIÓN (A) + candidatas de aporte
  type Core = { h: Holding; tier: ValTier; m: number | null; composite: number | null; reliable: boolean;
    positionAction: PositionAction; positionWhy: string; favor: string[]; penalize: string[];
    evidence: string[]; risks: string[]; missing: string[]; confidence: "alta" | "media" | "baja";
    marginLine: string; accumEligible: boolean; };
  const cores: Core[] = [];
  for (const h of holdings) {
    const t = h.ticker.toUpperCase();
    const s = scanBy.get(t); const fvS = fv[t]; const projS = proj?.[t]; const q = qual?.[t];
    const riskPct = riskBy.get(t) ?? null;
    const mv = h.marketValue ?? 0; const overW = h.weight > constraints.maxWeightAsset;
    const highRisk = riskPct != null && riskPct > MAX_RISK;
    const mLine = marginLineOf(fvS); const composite = s?.composite ?? null; const knownStale = !!q && q.fresh === false;
    const projLine = projS ? `Proyección 12m (estadística): mediana ${projS.ret12mP50 >= 0 ? "+" : ""}${pctS(projS.ret12mP50)}, rango ${pctS(projS.ret12mP5)}…+${pctS(projS.ret12mP95)}.` : null;
    let tier: ValTier;
    if (isEtf(h.assetClass) || isCommodity(h.ticker, h.assetClass)) tier = "vehiculo";
    else if (!fvS || !fvS.available) tier = "sin-datos";
    else if (!fvS.priceComparable || fvS.confidence === "Baja" || (fvS.marginBase != null && fvS.marginBase > MARGIN_IMPLAUSIBLE)) tier = "preliminar";
    else tier = "confiable";
    const reliable = tier === "confiable" && fvS!.marginBase != null;
    const m = reliable ? fvS!.marginBase! : null;
    const favor: string[] = []; const penalize: string[] = [];
    if (composite != null) (composite >= SCAN_ATTRACTIVE ? favor : penalize).push(`Atractivo del scanner ${Math.round(composite)}/100`);
    if (projS) (projS.ret12mP50 >= 0 ? favor : penalize).push(`Proyección 12m mediana ${pctS(projS.ret12mP50)}`);
    if (knownStale) penalize.push("Fundamentales no recientes");

    let positionAction: PositionAction; let positionWhy: string;
    let confidence: "alta" | "media" | "baja" = "media";
    let accumEligible = false;
    const evidence = [mLine, composite != null ? `Score ${Math.round(composite)}/100.` : "", projLine ?? "", `Peso ${pctS(h.weight)}${riskPct != null ? `, ${pctS(riskPct)} del riesgo` : ""}.`].filter(Boolean);
    const risks: string[] = []; const missing: string[] = [];

    if (tier === "vehiculo") {
      if (overW || highRisk) { positionAction = "REDUCIR"; positionWhy = `Concentración por encima de tu límite (${overW ? `peso ${pctS(h.weight)}` : `riesgo ${pctS(riskPct!)}`}).`; favor.push("Baja concentración/riesgo"); }
      else { positionAction = "MANTENER"; positionWhy = `Vehículo diversificado dentro de límites: cumple su rol (se evalúa por cartera, no por DCF).`; favor.push(isCommodity(h.ticker, h.assetClass) ? "Oro/plata: descorrelación" : "Cesta amplia de empresas"); }
      penalize.push(isCommodity(h.ticker, h.assetClass) ? "Sin flujos: valor por spot" : "Posible solapamiento con tus acciones");
      risks.push("Posible solapamiento (ver X-Ray)."); missing.push("No aplica Fair Value por empresa a un vehículo.");
    } else if (mv > 0 && h.weight < STUB_W) {
      positionAction = "REVISAR"; positionWhy = `Posición ínfima (${pctS(h.weight)}, ${usd(mv)}): tamaño inmaterial → revisar. Una venta exige además una razón económica o de riesgo, no sólo el tamaño.`;
      confidence = "baja"; favor.push("Revisar posición de tamaño inmaterial"); penalize.push("Tamaño inmaterial"); risks.push("No se vende sólo por tamaño: hace falta señal de valoración o de riesgo."); missing.push("Justificación económica/riesgo para decidir una venta.");
    } else if (overW || highRisk) {
      positionAction = "REDUCIR"; positionWhy = `${overW ? `Pesa ${pctS(h.weight)} (límite ${pctS(constraints.maxWeightAsset)})` : `Concentra ${pctS(riskPct!)} del riesgo (> ${pctS(MAX_RISK)})`}.`;
      confidence = highRisk ? "alta" : "media"; favor.push("Baja la concentración/riesgo"); penalize.push(overW ? "Peso sobre el límite" : "Riesgo dominante");
      risks.push("Recortar un ganador reduce recorrido; considera impuestos/costos.");
      if (reliable && m! > MARGIN_UNDER) penalize.push("Parece infravalorada: recorte por riesgo, no por precio");
    } else if (reliable && m != null) {
      if (m <= MARGIN_STRONG_OVER && composite != null && composite < SCAN_WEAK) {
        positionAction = "REDUCIR"; positionWhy = `Muy sobrevalorada (${pctS(m)}) y atractivo débil (${Math.round(composite)}/100): recorte parcial.`;
        favor.push("Reduce exposición a nombre caro y poco atractivo"); penalize.push("FV V1 preliminar: recorte parcial, no venta total");
        risks.push("Si el crecimiento supera tus supuestos, la sobrevaloración puede ser aparente.");
      } else {
        positionAction = "MANTENER";
        positionWhy = m >= MARGIN_UNDER ? `Infravalorada (${m >= 0 ? "+" : ""}${pctS(m)}) y dentro de límites: conservar.`
          : m <= MARGIN_STRONG_OVER ? `Parece muy cara (${pctS(m)}) pero el atractivo no es débil: no se vende por un solo DCF.`
          : m <= -MARGIN_UNDER ? `Algo cara (${pctS(m)}) pero dentro de tolerancia y límites: conservar.`
          : `Precio en rango razonable del Fair Value y dentro de límites: conservar.`;
        risks.push("El Fair Value V1 es preliminar; una señal aislada no basta para vender.");
        // Candidata de ACUMULAR (aporte) si infravalorada o razonable+atractiva, con espacio.
        const undervalued = m >= MARGIN_UNDER; const fairAttr = m > -MARGIN_UNDER && composite != null && composite >= SCAN_ATTRACTIVE;
        if ((undervalued || fairAttr) && composite != null && composite >= SCAN_WEAK && !knownStale && mv < capPerAsset - 1e-6) accumEligible = true;
      }
    } else if (tier === "preliminar") {
      const implausible = fvS!.marginBase != null && fvS!.marginBase > MARGIN_IMPLAUSIBLE;
      positionAction = "REVISAR";
      positionWhy = implausible ? `Fair Value +${pctS(fvS!.marginBase!)} implausible (artefacto del DCF): sin conclusión de valoración; posición dentro de límites de riesgo.`
        : !fvS!.priceComparable ? `Valoración no comparable (ADR/FX): sin conclusión por valoración; posición dentro de límites de riesgo.`
        : `Confianza de valoración baja: sin conclusión por valoración; posición dentro de límites de riesgo.`;
      confidence = "baja"; penalize.push(implausible ? "Fair Value desmesurado: revisar" : "Margen no comparable/confiable todavía");
      risks.push("Sin valoración comparable no se concluye comprar/vender por precio; sólo gestión de riesgo.");
      missing.push(implausible ? "FCF normalizado por ciclo (cíclicas)." : !fvS!.priceComparable ? "FX fechado para comparar precio y valor (ADR/moneda)." : "Mejor cobertura de fundamentales.");
    } else {
      positionAction = "REVISAR"; positionWhy = `Sin datos para valorar (financiera o insuficiente): sin conclusión por valoración; posición dentro de límites de riesgo.`;
      confidence = "baja"; penalize.push("Sin Fair Value"); risks.push("Sin Fair Value no se concluye por valoración; sólo gestión de riesgo.");
      missing.push("Fair Value ausente (p. ej. banca/aseguradora o datos insuficientes).");
    }
    cores.push({ h, tier, m, composite, reliable, positionAction, positionWhy, favor, penalize, evidence, risks, missing, confidence, marginLine: mLine, accumEligible });
  }

  // ─────────── Paso 2: Oportunidades fuera de cartera (ruta B)
  const opportunities: Opp2[] = scan
    .filter((s) => !held.has(s.ticker.toUpperCase()) && s.composite >= SCAN_STRONG)
    .sort((a, b) => b.composite - a.composite).slice(0, 8)
    .map((s) => {
      const t = s.ticker.toUpperCase(); const fvS = fv[t]; const mLine = marginLineOf(fvS);
      const usable = !!fvS && fvS.available && fvS.priceComparable && fvS.marginBase != null && (fvS.confidence === "Alta" || fvS.confidence === "Media");
      const m = usable ? fvS!.marginBase! : null;
      let action: Opp2["action"]; let note: string; let eligible = false;
      if (!fvS || !fvS.available || !usable) { action = "INVESTIGAR"; note = "Atractivo alto pero sin Fair Value comparable: no se compra sin valoración."; }
      else if (m! > MARGIN_IMPLAUSIBLE) { action = "INVESTIGAR"; note = `Atractivo alto y margen +${pctS(m!)} implausible (artefacto del DCF): revisar, no comprar.`; }
      else if (m! >= MARGIN_UNDER) { action = "COMPRAR"; eligible = true; note = `Atractivo alto e infravalorada (${m! >= 0 ? "+" : ""}${pctS(m!)}): candidata a desplegar.`; }
      else if (m! <= -MARGIN_UNDER) { action = "ESPERAR"; note = `Atractivo alto pero sobrevalorada (${pctS(m!)}): esperar mejor precio.`; }
      else { action = "OBSERVAR"; note = "Atractivo alto y precio en rango: en observación."; }
      return { ticker: s.ticker, name: s.name ?? null, sector: s.sector, composite: s.composite, action, marginLine: mLine, note, eligible };
    });

  // ─────────── Paso 3: Mejor ETF diversificador (ruta C) — reduce HHI efectivo sin empeorar el sesgo
  let bestEtf: { r: EtfRouteInput; dHhi: number; dTech: number } | null = null;
  if (effBefore && etfRoutes) {
    for (const r of etfRoutes) {
      if (r.currentValue >= capPerAsset - 1e-6) continue;
      const dHhi = effBefore.hhi - r.hhiAfter; const dTech = effBefore.tech - r.techAfter;
      if (dHhi <= HHI_MATERIAL) continue;
      if (dTech < -0.005) continue;                 // descarta si sube materialmente la tecnología
      if (!bestEtf || dHhi > bestEtf.dHhi) bestEtf = { r, dHhi, dTech };
    }
  }

  // ─────────── Paso 4: ASIGNACIÓN del aporte por CONVICCIÓN (B)
  const accumCands = cores.filter((c) => c.accumEligible).map((c) => ({ ticker: c.h.ticker, current: c.h.marketValue ?? 0, composite: c.composite ?? 0, margin: c.m ?? 0 }));
  const oppCands = opportunities.filter((o) => o.eligible).map((o) => ({ ticker: o.ticker, current: 0, composite: o.composite }));
  const hasStrong = accumCands.length > 0 || oppCands.length > 0;

  let allocation: Alloc2[] = []; let invested = 0;
  const contribByTicker = new Map<string, { action: ContribAction; amount: number; why: string }>();
  const routesChosen = new Set<"A" | "B" | "C">();

  if (cashInt > 0 && hasStrong) {
    // Convicción por VALORACIÓN ⇒ desplegar el aporte completo entre las candidatas con margen.
    type Cand = { ticker: string; route: "A" | "B"; kind: Alloc2["kind"]; current: number; rank: number };
    const cands: Cand[] = [];
    for (const a of accumCands) cands.push({ ticker: a.ticker, route: "A", kind: "acumular", current: a.current, rank: 100 + a.margin * 100 });
    for (const o of oppCands) cands.push({ ticker: o.ticker, route: "B", kind: "nueva", current: 0, rank: 80 + o.composite / 10 });
    cands.sort((a, b) => b.rank - a.rank);
    const sel = cands.slice(0, MAX_ALLOC_ITEMS);
    const rooms = new Map<string, number>(); for (const c of sel) rooms.set(c.ticker, Math.max(0, capPerAsset - c.current));
    const rounded = roundToBudget(sel.map((c) => ({ ticker: c.ticker, amount: waterfill(rooms, Math.round(cashInt * DEPLOY_STRONG)).get(c.ticker) ?? 0 })).filter((r) => r.amount > 0.5), Math.round(cashInt * DEPLOY_STRONG));
    for (const c of sel) {
      const amt = rounded[c.ticker] ?? 0; if (amt <= 0) continue;
      invested += amt; routesChosen.add(c.route);
      allocation.push({ ticker: c.ticker, route: c.route, kind: c.kind, amount: amt, pctOfCash: amt / cashInt, newWeight: (c.current + amt) / denom, reason: c.route === "A" ? "Aumentar: infravalorada/razonable y atractiva (convicción por valoración)." : "Nueva: infravalorada y atractiva (convicción por valoración).", marginLine: marginLineOf(fv[c.ticker.toUpperCase()]) });
      contribByTicker.set(c.ticker.toUpperCase(), { action: "ACUMULAR", amount: amt, why: "Infravalorada/atractiva: convicción por valoración para aportar." });
    }
  } else if (cashInt > 0 && bestEtf) {
    // Convicción por DIVERSIFICACIÓN (sin valoración) ⇒ despliegue PARCIAL, liquidez residual justificada.
    const room = Math.max(0, capPerAsset - bestEtf.r.currentValue);
    const target = Math.min(Math.round(cashInt * DEPLOY_DIVERSIFIER), Math.round(room));
    if (target > 0) {
      invested = target; routesChosen.add("C");
      allocation.push({ ticker: bestEtf.r.ticker, route: "C", kind: "etf", amount: target, pctOfCash: target / cashInt, newWeight: (bestEtf.r.currentValue + target) / denom, reason: `Diversificación (convicción media, sin valoración): despliegue parcial del ${pctS(DEPLOY_DIVERSIFIER)} del aporte; el resto queda como liquidez.`, marginLine: "Evaluado por metodología de cartera (look-through), no por DCF." });
      contribByTicker.set(bestEtf.r.ticker.toUpperCase(), { action: "ACUMULAR", amount: target, why: `Mejor diversificador (reduce concentración efectiva, baja tecnología): aporte parcial por convicción media.` });
    }
  }
  const cashKept = cashInt - invested;

  // Acción de APORTE (B) para el resto de tenencias: ESPERAR con motivo concreto.
  for (const c of cores) {
    const t = c.h.ticker.toUpperCase();
    if (contribByTicker.has(t)) continue;
    let why: string;
    if (c.tier === "vehiculo") {
      const rr = etfRoutes?.find((e) => e.ticker.toUpperCase() === t);
      why = isCommodity(c.h.ticker, c.h.assetClass) ? "No mejora la diversificación de empresas; rol ya cubierto."
        : rr && effBefore && (effBefore.tech - rr.techAfter) < -0.005 ? "Aportar aquí subiría tu exposición tecnológica (diversifica menos que la opción elegida)."
        : "Diversifica menos que la opción elegida este mes.";
    } else if (c.reliable && c.m != null && c.m <= -MARGIN_UNDER) why = "Sobrevalorada: no se aporta a un nombre caro.";
    else if (c.tier === "preliminar") why = "Valoración no comparable (ADR/FX): no se aporta sin valoración fundada.";
    else if (c.tier === "sin-datos") why = "Sin Fair Value: no se aporta sin valoración.";
    else why = "Dentro de rango; sin ventaja de valoración para aportar este mes.";
    contribByTicker.set(t, { action: "ESPERAR", amount: 0, why });
  }

  // ─────────── Ensamblar recomendaciones (A + B por instrumento)
  const recommendations: Rec2[] = cores.map((c) => {
    const cb = contribByTicker.get(c.h.ticker.toUpperCase())!;
    const sev = (c.positionAction === "REDUCIR" ? 80 : c.positionAction === "VENDER" ? 40 : c.positionAction === "REVISAR" ? 34 : 20)
      + (cb.action === "ACUMULAR" ? 25 : 0) + c.h.weight * 40;
    return {
      ticker: c.h.ticker, name: c.h.name, tier: c.tier,
      positionAction: c.positionAction, positionWhy: c.positionWhy,
      contribAction: cb.action, contribWhy: cb.why, contribAmount: cb.action === "ACUMULAR" ? cb.amount : null,
      favor: c.favor, penalize: c.penalize, evidence: c.evidence, risks: c.risks, missing: c.missing,
      confidence: c.confidence, marginLine: c.marginLine, severity: sev,
    };
  }).sort((a, b) => b.severity - a.severity);

  // ─────────── Rutas A/B/C/D
  const bestA = accumCands.sort((a, b) => b.margin - a.margin)[0] ?? null;
  const bestB = opportunities.find((o) => o.eligible) ?? null;
  const routes: RouteEval[] = [
    bestA ? { id: "A", label: "Aumentar posiciones existentes", available: true, chosen: routesChosen.has("A"), amount: allocation.filter((a) => a.route === "A").reduce((s, a) => s + a.amount, 0), merit: `${bestA.ticker}: infravalorada/razonable y atractiva.`, whyNot: null, detail: [] }
         : { id: "A", label: "Aumentar posiciones existentes", available: false, chosen: false, amount: 0, merit: "", whyNot: "Tus acciones están caras (sobrevaloradas) o con valoración no comparable (ADR/FX): ninguna ofrece margen de seguridad hoy.", detail: [] },
    bestB ? { id: "B", label: "Comprar oportunidades nuevas", available: true, chosen: routesChosen.has("B"), amount: allocation.filter((a) => a.route === "B").reduce((s, a) => s + a.amount, 0), merit: `${bestB.ticker}: atractivo alto e infravalorada.`, whyNot: null, detail: [] }
         : { id: "B", label: "Comprar oportunidades nuevas", available: false, chosen: false, amount: 0, merit: "", whyNot: "Las candidatas del scanner están sobrevaloradas, son financieras sin DCF, o tienen margen implausible: ninguna es una compra creíble.", detail: [] },
    bestEtf ? { id: "C", label: "Aportar a ETF diversificado", available: true, chosen: routesChosen.has("C"), amount: allocation.filter((a) => a.route === "C").reduce((s, a) => s + a.amount, 0), merit: `${bestEtf.r.ticker} reduce la concentración efectiva (${effN(effBefore!.hhi).toFixed(1)}→${effN(bestEtf.r.hhiAfter).toFixed(1)} nombres) y baja la exposición tecnológica (${pctS(effBefore!.tech)}→${pctS(bestEtf.r.techAfter)}). Despliegue parcial por convicción media.`, whyNot: null, detail: [] }
            : { id: "C", label: "Aportar a ETF diversificado", available: false, chosen: false, amount: 0, merit: "", whyNot: "Los ETF disponibles no mejoran materialmente la diversificación efectiva o concentran más tecnología.", detail: [] },
    { id: "D", label: "Mantener liquidez", available: true, chosen: cashKept > 0, amount: cashKept, merit: cashKept > 0 ? `Pólvora seca: sin compra de alta convicción (infravalorada) este mes, se conserva ${usd(cashKept)} para una mejor oportunidad.` : "Preserva opción de comprar más barato.", whyNot: null, detail: [] },
  ];

  // ─────────── Concentración efectiva antes/después (la caja NO es posición)
  const beforeEffN = effBefore ? effN(effBefore.hhi) : effN(hhiFrom(holdings.filter((h) => h.marketValue).map((h) => h.weight)));
  let afterEffN = beforeEffN;
  const chosenEtf = allocation.find((a) => a.route === "C");
  // Interpolación de efN si el ETF recibió un aporte PARCIAL (el etfRoute asume el aporte completo).
  if (chosenEtf && etfRoutes) {
    const rr = etfRoutes.find((e) => e.ticker.toUpperCase() === chosenEtf.ticker.toUpperCase());
    if (rr && cashInt > 0) { const frac = chosenEtf.amount / cashInt; afterEffN = beforeEffN + (rr.effNamesAfter - beforeEffN) * frac; }
  }
  const topBeforeH = holdings.filter((h) => h.marketValue).sort((a, b) => b.weight - a.weight)[0] ?? null;
  const afterVals: Record<string, number> = {}; for (const h of holdings) afterVals[h.ticker] = h.marketValue ?? 0;
  for (const it of allocation) afterVals[it.ticker] = (afterVals[it.ticker] ?? 0) + it.amount;
  const afterTotalInvested = Object.values(afterVals).reduce((a, b) => a + b, 0);
  const topAfter = Object.entries(afterVals).map(([t, v]) => ({ t, w: afterTotalInvested > 0 ? v / afterTotalInvested : 0 })).sort((a, b) => b.w - a.w)[0] ?? null;

  const stance: Advisor2Report["stance"] = invested <= 0 ? "esperar" : cashKept > 0 ? "parcial" : "desplegar";
  const cashNote = "La concentración se mide sobre las posiciones invertidas (look-through). El efectivo no es una posición: no diluye el peso de tus acciones; se informa aparte como liquidez disponible.";
  let monthSummary: string;
  if (invested <= 0) monthSummary = cashInt > 0
    ? "Mantener el aporte en liquidez es la decisión justificada hoy: no hay compra de alta convicción (infravalorada), ni un ETF que mejore materialmente tu diversificación."
    : "Sin aporte a desplegar; revisa las acciones por posición.";
  else {
    const names = allocation.map((a) => `${a.ticker} ${usd(a.amount)}`).join(", ");
    monthSummary = `Aportar ${usd(invested)} de ${usd(cashInt)} (${names})${cashKept > 0 ? ` y mantener ${usd(cashKept)} como liquidez/pólvora seca` : ""}. Diversificación efectiva ${beforeEffN.toFixed(1)}→${afterEffN.toFixed(1)} nombres. Decisiones de posición y de aporte están separadas por instrumento abajo.`;
  }

  const warnings: string[] = [];
  const noComp = holdings.filter((h) => { const s = fv[h.ticker.toUpperCase()]; return s?.available && !s.priceComparable; }).map((h) => h.ticker);
  const noFv = holdings.filter((h) => !isEtf(h.assetClass) && !isCommodity(h.ticker, h.assetClass) && !fv[h.ticker.toUpperCase()]?.available).map((h) => h.ticker);
  if (noComp.length) warnings.push(`Valoración preliminar por moneda (ADR/FX) ⇒ posición en REVISAR, no se descarta la inversión: ${noComp.join(", ")}.`);
  if (noFv.length) warnings.push(`Sin Fair Value ⇒ posición en REVISAR: ${noFv.join(", ")}.`);
  if (!scanAsOf) warnings.push("Fecha del scanner no disponible en esta carga.");
  warnings.push("Fair Value V1 es preliminar (DCF de FCFE con OCF−CAPEX aproximado); los modelos A/B experimentales NO se usan como señal.");

  const rules = [
    "DOS decisiones por instrumento: A) posición existente (MANTENER/REDUCIR/VENDER/REVISAR) y B) aporte nuevo (ACUMULAR/COMPRAR/ESPERAR). No son contradictorias.",
    "MANTENER es una conclusión fundamentada (valorada y dentro de límites, o vehículo en su rol). Si faltan datos para concluir ⇒ REVISAR (no un MANTENER disfrazado).",
    `ACUMULAR (aporte) exige convicción por valoración: infravalorada ≥ +${pctS(MARGIN_UNDER)} con atractivo ≥ ${SCAN_WEAK}, o razonable con atractivo ≥ ${SCAN_ATTRACTIVE}.`,
    `REDUCIR exige evidencia dura: peso > ${pctS(constraints.maxWeightAsset)}, riesgo > ${pctS(MAX_RISK)}, o muy sobrevalorada + atractivo < ${SCAN_WEAK}. Nunca venta total por un solo DCF.`,
    `Aporte por CONVICCIÓN: valoración ⇒ despliegue completo; diversificación (ETF, sin valoración) ⇒ despliegue parcial (${pctS(DEPLOY_DIVERSIFIER)}) con liquidez residual. Sin mínimo de compras ni máximo artificial de efectivo.`,
    "No se optimiza sólo la concentración: un ETF sólo entra si reduce la concentración efectiva SIN subir materialmente el sesgo sectorial dominante.",
  ];
  const dataUsed = [
    `Posiciones reales (valor ${usd(V)}; ${holdings.length} instrumento(s)).`,
    "Fair Value: DCF de FCFE por empresa; exposición efectiva por X-Ray (look-through de ETF).",
    scanAsOf ? `Scanner del ${scanAsOf} (atractivo relativo).` : "Scanner: snapshot más reciente.",
    risk ? "Riesgo: covarianzas históricas (motor de Proyección)." : "Sin modelo de riesgo cargado.",
    `Límites: ${pctS(constraints.maxWeightAsset)} por activo, ${pctS(constraints.maxWeightSector)} por sector.`,
  ];

  return {
    monthSummary, stance, portfolioValue: V, cash: cashInt, invested, cashKept, allocation, routes,
    before: { effN: beforeEffN, topWeight: topBeforeH?.weight ?? 0, topTicker: topBeforeH?.ticker ?? null },
    after: { effN: afterEffN, topWeight: topAfter?.w ?? 0, topTicker: topAfter?.t ?? null },
    cashNote, recommendations, opportunities, warnings, rules, dataUsed,
  };
}
