// Investment Advisor 2.1 — recomendaciones DETERMINÍSTICAS, valuation-aware y GRADUADAS.
// Integra Fair Value (margen de seguridad FCFE), calidad/actualidad, riesgo/concentración,
// exposición efectiva (look-through de ETF), proyección y scanner. El Fair Value es una SEÑAL
// IMPORTANTE pero NO una condición obligatoria universal para invertir.
//
// Cambios 2.1 (utilidad):
//  - Valoración ≠ elegibilidad: se distinguen tenencias con valoración CONFIABLE, PRELIMINAR
//    (FX/confianza/margen implausible), VEHÍCULO (ETF por cartera, no DCF) y SIN DATOS (abstención).
//  - Ruta de aportación por ETF diversificado, evaluada por concentración efectiva y solapamiento,
//    sin exigir Fair Value individual.
//  - Reglas menos binarias: margen > +60% es ALERTA de revisión (no invalida otras señales);
//    ACUMULAR admite confianza media sin exigir que todos los indicadores sean favorables.
//  - Comparación explícita de rutas A (aumentar) / B (nuevas) / C (ETF diversificado) / D (liquidez),
//    eligiendo la combinación más razonable y explicando por qué se descartan las demás.
//  - El 100% en efectivo es una decisión JUSTIFICADA, no el residuo de filtros demasiado estrictos.
//  - Los modelos A/B experimentales NO se usan como señal.

import type { Holding, Constraints, RiskModel } from "./advisor";
import { hhiFrom } from "./advisor";

export type Action2 = "COMPRAR" | "ACUMULAR" | "MANTENER" | "REDUCIR" | "VENDER" | "ESPERAR";
export type ValTier = "confiable" | "preliminar" | "vehiculo" | "sin-datos";

export interface FvSummary {
  available: boolean; priceComparable: boolean;
  marginBase: number | null; marginConservative: number | null; marginOptimista: number | null;
  confidence: "Alta" | "Media" | "Baja" | null; currency: string | null; reason?: string;
}
export interface ProjSummary { ret12mP50: number; ret12mP5: number; ret12mP95: number; annVol: number; }
export interface QualSummary { fresh: boolean; asOf: string | null; }
// Métrica de ruta ETF (exposición efectiva look-through calculada en la página con X-Ray).
export interface EtfRouteInput {
  ticker: string; currentValue: number;
  effNamesAfter: number; hhiAfter: number; techAfter: number;  // tras añadir el aporte
  topSector?: string | null;
}

export interface Rec2 {
  ticker: string; name: string | null; action: Action2; tier: ValTier;
  why: string; favor: string[]; penalize: string[]; evidence: string[]; risks: string[]; missing: string[];
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
  cashNote: string;
  recommendations: Rec2[]; opportunities: Opp2[]; warnings: string[]; rules: string[]; dataUsed: string[];
}

export interface Advisor2Input {
  holdings: Holding[];
  scan: { ticker: string; name?: string | null; sector: string | null; composite: number }[];
  cash: number; constraints: Constraints;
  fv: Record<string, FvSummary>;
  proj?: Record<string, ProjSummary>;
  qual?: Record<string, QualSummary>;
  risk?: RiskModel;
  etfRoutes?: EtfRouteInput[];
  effBefore?: { effN: number; hhi: number; tech: number };
  scanAsOf?: string;
}

const MARGIN_UNDER = 0.10, MARGIN_STRONG_UNDER = 0.20, MARGIN_STRONG_OVER = -0.25, MARGIN_IMPLAUSIBLE = 0.60;
const SCAN_STRONG = 65, SCAN_ATTRACTIVE = 55, SCAN_WEAK = 40, MAX_RISK = 0.45, STUB_W = 0.015, MAX_ALLOC_ITEMS = 5;
const HHI_MATERIAL = 0.002; // mejora mínima de HHI efectivo para considerar que un ETF diversifica

const pctS = (x: number) => `${(x * 100).toFixed(1)}%`;
const usd = (x: number) => `${Math.round(x).toLocaleString("en-US")} USD`;
const effN = (hhi: number) => (hhi > 0 ? 1 / hhi : 0);
const isEtf = (a: string | null | undefined) => ["etf", "fund", "etn", "mutualfund"].includes((a ?? "").toLowerCase());
const isCommodity = (t: string, a: string | null | undefined) =>
  ["GLD", "SLV", "IAU", "PPLT", "PALL", "SGOL", "SIVR"].includes(t.toUpperCase()) || (a ?? "").toLowerCase() === "commodity";

function marginLineOf(s: FvSummary | undefined): string {
  if (!s || !s.available) return `Fair Value no disponible${s?.reason ? ` (${s.reason})` : ""}.`;
  if (!s.priceComparable || s.marginBase == null)
    return `Fair Value ${s.currency ?? ""} calculado, margen vs. precio no comparable (requiere FX fechado).`;
  const m = s.marginBase;
  const bucket = m > MARGIN_IMPLAUSIBLE ? "margen implausible (posible artefacto del DCF)"
    : m >= MARGIN_STRONG_UNDER ? "muy infravalorada" : m >= MARGIN_UNDER ? "infravalorada"
    : m <= MARGIN_STRONG_OVER ? "muy sobrevalorada" : m <= -MARGIN_UNDER ? "sobrevalorada" : "en rango razonable";
  return `Margen de seguridad (base) ${m >= 0 ? "+" : ""}${pctS(m)} — ${bucket} (confianza ${s.confidence}).`;
}

function roundToBudget(raw: { ticker: string; amount: number }[], budget: number): Record<string, number> {
  const target = Math.min(Math.round(budget), Math.round(raw.reduce((a, r) => a + r.amount, 0)));
  const parts = raw.map((r) => ({ t: r.ticker, floor: Math.floor(r.amount), frac: r.amount - Math.floor(r.amount) }));
  let used = parts.reduce((a, p) => a + p.floor, 0);
  let rem = target - used;
  parts.sort((a, b) => b.frac - a.frac);
  for (let i = 0; i < parts.length && rem > 0; i++) { parts[i].floor += 1; rem -= 1; }
  const out: Record<string, number> = {};
  for (const p of parts) out[p.t] = p.floor;
  return out;
}
function waterfill(rooms: Map<string, number>, cash: number): Map<string, number> {
  const alloc = new Map<string, number>();
  for (const k of rooms.keys()) alloc.set(k, 0);
  let remaining = cash;
  let active = [...rooms.keys()].filter((k) => rooms.get(k)! > 1e-9);
  for (let guard = 0; guard < 200 && remaining > 1e-6 && active.length > 0; guard++) {
    const share = remaining / active.length;
    const next: string[] = []; let progressed = false;
    for (const k of active) {
      const canTake = rooms.get(k)! - alloc.get(k)!;
      const take = Math.min(share, canTake);
      if (take > 1e-9) { alloc.set(k, alloc.get(k)! + take); remaining -= take; progressed = true; }
      if (rooms.get(k)! - alloc.get(k)! > 1e-6) next.push(k);
    }
    active = next;
    if (!progressed) break;
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
  const denom = V + cashInt;
  const capPerAsset = constraints.maxWeightAsset * denom;

  const recommendations: Rec2[] = [];
  const accumA: { ticker: string; current: number; composite: number; margin: number; conf: string }[] = [];

  for (const h of holdings) {
    const t = h.ticker.toUpperCase();
    const s = scanBy.get(t); const fvS = fv[t]; const projS = proj?.[t]; const q = qual?.[t];
    const riskPct = riskBy.get(t) ?? null;
    const mv = h.marketValue ?? 0; const overW = h.weight > constraints.maxWeightAsset;
    const highRisk = riskPct != null && riskPct > MAX_RISK;
    const mLine = marginLineOf(fvS);
    const composite = s?.composite ?? null;
    const knownStale = !!q && q.fresh === false;
    const projLine = projS ? `Proyección 12m (estadística): mediana ${projS.ret12mP50 >= 0 ? "+" : ""}${pctS(projS.ret12mP50)}, rango ${pctS(projS.ret12mP5)}…+${pctS(projS.ret12mP95)}.` : null;
    // Tier de valoración
    let tier: ValTier;
    if (isEtf(h.assetClass) || isCommodity(h.ticker, h.assetClass)) tier = "vehiculo";
    else if (!fvS || !fvS.available) tier = "sin-datos";
    else if (!fvS.priceComparable || fvS.confidence === "Baja" || (fvS.marginBase != null && fvS.marginBase > MARGIN_IMPLAUSIBLE)) tier = "preliminar";
    else tier = "confiable";
    const reliable = tier === "confiable" && fvS!.marginBase != null;
    const m = reliable ? fvS!.marginBase! : null;

    // Vehículos (ETF / materia prima)
    if (tier === "vehiculo") {
      const act: Action2 = overW ? "REDUCIR" : "MANTENER";
      recommendations.push({
        ticker: h.ticker, name: h.name, action: act, tier,
        why: act === "REDUCIR" ? `Recortar ${h.ticker}: concentración por encima de tu límite.` : `Mantener ${h.ticker}: vehículo diversificado (se evalúa por cartera, no por DCF).`,
        favor: act === "REDUCIR" ? [] : ["Aporta diversificación/look-through", isCommodity(h.ticker, h.assetClass) ? "Oro/plata: descorrelación y cobertura" : "Cesta amplia de empresas"],
        penalize: [overW ? `Peso ${pctS(h.weight)} sobre el límite` : "Posible solapamiento con tus acciones (ver X-Ray)"],
        evidence: [`Peso ${pctS(h.weight)}${riskPct != null ? `, ${pctS(riskPct)} del riesgo` : ""}.`, isCommodity(h.ticker, h.assetClass) ? "Materia prima: sin flujos; valor por spot." : "ETF: valoración look-through de subyacentes."],
        risks: ["Posible solapamiento con otras posiciones."], missing: ["No aplica Fair Value por empresa a un vehículo."],
        confidence: "media", marginLine: "Vehículo diversificado — evaluado por metodología de cartera.", severity: (act === "REDUCIR" ? 78 : 16) + h.weight * 40,
      });
      continue;
    }
    // Higiene
    if (mv > 0 && h.weight < STUB_W) {
      recommendations.push({
        ticker: h.ticker, name: h.name, action: "VENDER", tier,
        why: `Cerrar ${h.ticker}: posición ínfima (${pctS(h.weight)}).`,
        favor: ["Simplifica la cartera"], penalize: [`Peso ${pctS(h.weight)}: impacto inmaterial`],
        evidence: [`Peso ${pctS(h.weight)} (${usd(mv)}).`, mLine], risks: ["Mantener si construirás la posición pronto."],
        missing: ["Higiene, no valoración."], confidence: "media", marginLine: mLine, severity: 40,
      });
      continue;
    }
    // Gestión de riesgo (dura)
    if (overW || highRisk) {
      recommendations.push({
        ticker: h.ticker, name: h.name, action: "REDUCIR", tier,
        why: `Recortar ${h.ticker}: ${overW ? `pesa ${pctS(h.weight)} (límite ${pctS(constraints.maxWeightAsset)})` : `concentra ${pctS(riskPct!)} del riesgo`}.`,
        favor: ["Baja la concentración/riesgo de la cartera"],
        penalize: [overW ? `Peso ${pctS(h.weight)} sobre el límite` : `Aporte al riesgo ${pctS(riskPct!)} > ${pctS(MAX_RISK)}`, reliable && m! > MARGIN_UNDER ? "Parece infravalorada: recorte por riesgo, no por precio" : ""].filter(Boolean),
        evidence: [overW ? `Peso ${pctS(h.weight)} > límite.` : `Riesgo ${pctS(riskPct!)} (> ${pctS(MAX_RISK)}).`, mLine, projLine ?? ""].filter(Boolean),
        risks: ["Recortar un ganador reduce recorrido; considera impuestos/costos."], missing: [],
        confidence: highRisk ? "alta" : "media", marginLine: mLine, severity: (highRisk ? 90 : 82) + h.weight * 50,
      });
      continue;
    }

    const favor: string[] = []; const penalize: string[] = [];
    if (composite != null) (composite >= SCAN_ATTRACTIVE ? favor : penalize).push(`Atractivo del scanner ${Math.round(composite)}/100`);
    if (projS) (projS.ret12mP50 >= 0 ? favor : penalize).push(`Proyección 12m mediana ${pctS(projS.ret12mP50)} (estadística)`);
    if (knownStale) penalize.push("Fundamentales no recientes");

    if (reliable && m != null) {
      // (El margen implausible se clasifica como tier "preliminar" y se trata más abajo con alerta.)
      // ACUMULAR graduado: infravalorada (plausible) + atractivo ≥ débil, o razonable + atractivo sólido.
      const undervalued = m >= MARGIN_UNDER;
      const fairAndAttractive = m > -MARGIN_UNDER && composite != null && composite >= SCAN_ATTRACTIVE;
      if ((undervalued || fairAndAttractive) && composite != null && composite >= SCAN_WEAK && !knownStale && mv < capPerAsset - 1e-6) {
        favor.unshift(undervalued ? `Infravalorada (${m >= 0 ? "+" : ""}${pctS(m)})` : `Valoración razonable (${m >= 0 ? "+" : ""}${pctS(m)}) con atractivo sólido`);
        recommendations.push({
          ticker: h.ticker, name: h.name, action: "ACUMULAR", tier,
          why: `Acumular ${h.ticker}: ${undervalued ? "infravalorada" : "razonablemente valorada"} y con atractivo relativo ${composite >= SCAN_STRONG ? "fuerte" : "suficiente"}.`,
          favor, penalize: [...penalize, "Fair Value V1 preliminar (puede estrecharse)"],
          evidence: [mLine, `Score ${Math.round(composite)}/100.`, "Fundamentales recientes.", projLine ?? ""].filter(Boolean),
          risks: ["Fair Value V1 preliminar; el score no predice retorno."], missing: [],
          confidence: (fvS!.confidence === "Alta" && m >= MARGIN_STRONG_UNDER) ? "alta" : "media", marginLine: mLine, severity: 60 + Math.min(20, m * 40) + composite / 20,
        });
        accumA.push({ ticker: h.ticker, current: mv, composite, margin: m, conf: fvS!.confidence ?? "Media" });
        continue;
      }
      // REDUCIR por valoración CONVERGENTE: muy sobrevalorada + atractivo DÉBIL.
      if (m <= MARGIN_STRONG_OVER && composite != null && composite < SCAN_WEAK) {
        recommendations.push({
          ticker: h.ticker, name: h.name, action: "REDUCIR", tier,
          why: `Recortar parcialmente ${h.ticker}: muy sobrevalorada (${pctS(m)}) y atractivo débil.`,
          favor: ["Reduce exposición a un nombre caro y poco atractivo"], penalize: [...penalize, "Fair Value V1 preliminar: recorte parcial, no venta total"],
          evidence: [mLine, `Score ${Math.round(composite)}/100 (< ${SCAN_WEAK}).`, projLine ?? ""].filter(Boolean),
          risks: ["Si el crecimiento supera tus supuestos, la sobrevaloración puede ser aparente."], missing: [],
          confidence: "media", marginLine: mLine, severity: 70 + Math.min(20, -m * 40),
        });
        continue;
      }
      // MANTENER con matiz
      const nuance = m >= MARGIN_UNDER ? "infravalorada pero atractivo débil: no se fuerza compra"
        : m <= MARGIN_STRONG_OVER ? "parece muy cara pero el atractivo no es débil: no se vende por un solo DCF"
        : m <= -MARGIN_UNDER ? "algo cara pero dentro de tolerancia" : "precio en rango razonable del Fair Value";
      recommendations.push({
        ticker: h.ticker, name: h.name, action: "MANTENER", tier,
        why: `Mantener ${h.ticker}: ${nuance}.`, favor, penalize,
        evidence: [mLine, composite != null ? `Score ${Math.round(composite)}/100.` : "", projLine ?? "", `Peso ${pctS(h.weight)} dentro de límites.`].filter(Boolean),
        risks: ["El Fair Value V1 es preliminar; una señal aislada no basta."], missing: [],
        confidence: "media", marginLine: mLine, severity: 22 + h.weight * 20,
      });
      continue;
    }

    // Tier PRELIMINAR (FX / confianza baja / margen implausible): NO se descarta la inversión.
    if (tier === "preliminar") {
      const implausible = fvS!.marginBase != null && fvS!.marginBase > MARGIN_IMPLAUSIBLE;
      const reasonTxt = implausible ? `margen +${pctS(fvS!.marginBase!)} implausible — ALERTA de revisión (artefacto del DCF: FCF volátil/cíclico)`
        : !fvS!.priceComparable ? "precio y valor en distinta moneda (ADR/FX)" : "confianza baja";
      recommendations.push({
        ticker: h.ticker, name: h.name, action: "MANTENER", tier,
        why: `Mantener ${h.ticker}: valoración preliminar — ${reasonTxt}; se gestiona por riesgo, no se descarta la inversión.`,
        favor, penalize: [...penalize, implausible ? "Fair Value desmesurado: alerta de revisión, no de compra" : "Margen de seguridad no comparable/confiable todavía"],
        evidence: [mLine, composite != null ? `Score ${Math.round(composite)}/100.` : "", projLine ?? "", `Peso ${pctS(h.weight)} dentro de límites.`].filter(Boolean),
        risks: [implausible ? "El DCF sobrevalora FCF cíclicos/picos de margen: revisar con FCF normalizado." : "Sin margen comparable no se compra/vende por valoración; sólo gestión de riesgo."],
        missing: [implausible ? "FCF normalizado por ciclo (valoración de cíclicas pendiente)." : !fvS!.priceComparable ? "FX fechado para comparar precio y valor (ADR/moneda)." : "Mejor cobertura de fundamentales para subir la confianza."],
        confidence: "baja", marginLine: mLine, severity: 30 + h.weight * 20,
      });
      continue;
    }
    // Tier SIN-DATOS
    recommendations.push({
      ticker: h.ticker, name: h.name, action: "MANTENER", tier: "sin-datos",
      why: `Mantener ${h.ticker}: sin datos para una valoración (financiera o insuficiente); abstención por valoración.`,
      favor, penalize: [...penalize, "Sin Fair Value disponible"],
      evidence: [mLine, composite != null ? `Score ${Math.round(composite)}/100.` : "Sin score.", `Peso ${pctS(h.weight)} dentro de límites.`].filter(Boolean),
      risks: ["Sin Fair Value no se compra ni vende por valoración."], missing: ["Fair Value ausente (p. ej. banca/aseguradora o datos insuficientes)."],
      confidence: "baja", marginLine: mLine, severity: 28 + h.weight * 20,
    });
  }

  // ───────── Oportunidades fuera de cartera (ruta B)
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

  // ───────── Ruta C: mejor ETF diversificador (por concentración efectiva look-through)
  let bestEtf: { r: EtfRouteInput; dHhi: number; dTech: number } | null = null;
  if (effBefore && etfRoutes && etfRoutes.length) {
    for (const r of etfRoutes) {
      if (r.currentValue >= capPerAsset - 1e-6) continue;  // sin espacio bajo el tope
      const dHhi = effBefore.hhi - r.hhiAfter;   // >0 = reduce concentración
      const dTech = effBefore.tech - r.techAfter; // >0 = reduce tecnología
      if (dHhi <= HHI_MATERIAL) continue;         // sólo si diversifica de forma material
      if (!bestEtf || dHhi > bestEtf.dHhi) bestEtf = { r, dHhi, dTech };
    }
  }

  // ───────── Evaluación y elección de rutas A/B/C/D
  const bestA = accumA.sort((a, b) => (b.margin - a.margin) || (b.composite - a.composite))[0] ?? null;
  const bestB = opportunities.find((o) => o.eligible) ?? null;
  const routes: RouteEval[] = [];
  // A
  routes.push(bestA
    ? { id: "A", label: "Aumentar posiciones existentes", available: true, chosen: false, amount: 0,
        merit: `${bestA.ticker} reúne infravaloración (${bestA.margin >= 0 ? "+" : ""}${pctS(bestA.margin)}) y atractivo (${Math.round(bestA.composite)}/100).`, whyNot: null, detail: [] }
    : { id: "A", label: "Aumentar posiciones existentes", available: false, chosen: false, amount: 0, merit: "", whyNot: "Tus acciones están caras (sobrevaloradas) o con valoración no comparable (ADR/FX): ninguna ofrece margen de seguridad hoy.", detail: [] });
  // B
  routes.push(bestB
    ? { id: "B", label: "Comprar oportunidades nuevas", available: true, chosen: false, amount: 0, merit: `${bestB.ticker}: atractivo alto e infravalorada.`, whyNot: null, detail: [] }
    : { id: "B", label: "Comprar oportunidades nuevas", available: false, chosen: false, amount: 0, merit: "", whyNot: "Las candidatas del scanner están sobrevaloradas, son financieras sin DCF, o tienen margen implausible (artefacto): ninguna es una compra creíble.", detail: [] });
  // C
  routes.push(bestEtf
    ? { id: "C", label: "Aportar a ETF diversificado", available: true, chosen: false, amount: 0,
        merit: `${bestEtf.r.ticker} reduce la concentración efectiva (${effN(effBefore!.hhi).toFixed(1)}→${effN(bestEtf.r.hhiAfter).toFixed(1)} nombres) ${bestEtf.dTech > 0 ? `y baja la exposición tecnológica (${pctS(effBefore!.tech)}→${pctS(bestEtf.r.techAfter)})` : `(ojo: sube tecnología a ${pctS(bestEtf.r.techAfter)})`}.`,
        whyNot: null, detail: [] }
    : { id: "C", label: "Aportar a ETF diversificado", available: false, chosen: false, amount: 0, merit: "", whyNot: "Los ETF disponibles no mejorarían materialmente tu diversificación efectiva (o concentrarían más tecnología).", detail: [] });
  // D
  routes.push({ id: "D", label: "Mantener liquidez", available: true, chosen: false, amount: 0, merit: "Preserva opción de comprar más barato y no empeora la cartera.", whyNot: null, detail: [] });

  // Elección: candidatas elegibles (A: acumular, B: oportunidades, C: mejor ETF). Si ninguna aporta valor ⇒ D.
  type Cand = { ticker: string; route: "A" | "B" | "C"; kind: Alloc2["kind"]; current: number; rank: number };
  const cands: Cand[] = [];
  for (const a of accumA) cands.push({ ticker: a.ticker, route: "A", kind: "acumular", current: a.current, rank: 100 + a.margin * 100 });
  for (const o of opportunities) if (o.eligible) cands.push({ ticker: o.ticker, route: "B", kind: "nueva", current: 0, rank: 80 + o.composite / 10 });
  if (bestEtf) cands.push({ ticker: bestEtf.r.ticker, route: "C", kind: "etf", current: bestEtf.r.currentValue, rank: 70 + bestEtf.dHhi * 1000 });
  cands.sort((a, b) => b.rank - a.rank);
  const selected = cands.slice(0, MAX_ALLOC_ITEMS);

  let allocation: Alloc2[] = []; let invested = 0;
  if (cashInt > 0 && selected.length > 0) {
    const rooms = new Map<string, number>();
    for (const c of selected) rooms.set(c.ticker, Math.max(0, capPerAsset - c.current));
    const raw0 = waterfill(rooms, cashInt);
    const raw = selected.map((c) => ({ ticker: c.ticker, amount: raw0.get(c.ticker) ?? 0 })).filter((r) => r.amount > 0.5);
    const rounded = roundToBudget(raw, cashInt);
    invested = Object.values(rounded).reduce((a, b) => a + b, 0);
    allocation = selected.filter((c) => (rounded[c.ticker] ?? 0) > 0).map((c) => {
      const amt = rounded[c.ticker]; const newVal = c.current + amt; const fvS = fv[c.ticker.toUpperCase()];
      const reason = c.route === "C" ? `Diversificación: reduce tu concentración efectiva con la menor exposición tecnológica entre los ETF disponibles.`
        : c.route === "A" ? "Aumentar: infravalorada/razonable y atractiva; monto por diversificación con tope por activo."
        : "Candidata nueva infravalorada y atractiva; monto por diversificación con tope por activo.";
      for (const rt of routes) if (rt.id === c.route) { rt.chosen = true; rt.amount += amt; }
      return { ticker: c.ticker, route: c.route, kind: c.kind, amount: amt, pctOfCash: cashInt > 0 ? amt / cashInt : 0, newWeight: denom > 0 ? newVal / denom : 0, reason, marginLine: c.route === "C" ? "Evaluado por metodología de cartera (look-through), no por DCF." : marginLineOf(fvS) };
    });
  }
  const cashKept = cashInt - invested;
  if (cashKept > 0) for (const rt of routes) if (rt.id === "D") { rt.chosen = true; rt.amount = cashKept; }

  // Concentración efectiva antes/después (la caja NO es una posición: se informa aparte).
  const beforeEffN = effBefore ? effN(effBefore.hhi) : effN(hhiFrom(holdings.filter((h) => h.marketValue).map((h) => h.weight)));
  let afterEffN = beforeEffN;
  const chosenEtf = allocation.find((a) => a.route === "C");
  if (chosenEtf && etfRoutes) { const r = etfRoutes.find((e) => e.ticker.toUpperCase() === chosenEtf.ticker.toUpperCase()); if (r) afterEffN = r.effNamesAfter; }
  const topBeforeH = holdings.filter((h) => h.marketValue).sort((a, b) => b.weight - a.weight)[0] ?? null;
  const afterVals: Record<string, number> = {};
  for (const h of holdings) afterVals[h.ticker] = h.marketValue ?? 0;
  for (const it of allocation) afterVals[it.ticker] = (afterVals[it.ticker] ?? 0) + it.amount;
  const afterTotalInvested = Object.values(afterVals).reduce((a, b) => a + b, 0);
  const topAfter = Object.entries(afterVals).map(([t, v]) => ({ t, w: afterTotalInvested > 0 ? v / afterTotalInvested : 0 })).sort((a, b) => b.w - a.w)[0] ?? null;

  const stance: Advisor2Report["stance"] = invested <= 0 ? "esperar" : cashKept > 0 ? "parcial" : "desplegar";
  const cashNote = "La concentración se mide sobre las posiciones invertidas (look-through). El efectivo no es una posición: no diluye el peso de tus acciones; se informa aparte como liquidez disponible.";
  let monthSummary: string;
  if (invested <= 0) monthSummary = cashInt > 0
    ? "Mantener el aporte en liquidez es la decisión justificada hoy: aumentar tus acciones (caras), comprar candidatas nuevas (sin margen creíble) o aportar a un ETF (sin mejora de diversificación) no superan a esperar."
    : "Sin aporte a desplegar; revisa las recomendaciones por posición.";
  else {
    const chosen = routes.filter((r) => r.chosen && r.id !== "D").map((r) => r.id);
    monthSummary = `Desplegar ${usd(invested)} de ${usd(cashInt)} por la ruta ${chosen.join("+")} (${allocation.map((a) => a.ticker).join(", ")})${cashKept > 0 ? `; mantener ${usd(cashKept)} en liquidez` : ""}. Diversificación efectiva ${beforeEffN.toFixed(1)}→${afterEffN.toFixed(1)} nombres.`;
  }

  const warnings: string[] = [];
  const noComp = holdings.filter((h) => { const s = fv[h.ticker.toUpperCase()]; return s?.available && !s.priceComparable; }).map((h) => h.ticker);
  const noFv = holdings.filter((h) => !isEtf(h.assetClass) && !isCommodity(h.ticker, h.assetClass) && !fv[h.ticker.toUpperCase()]?.available).map((h) => h.ticker);
  if (noComp.length) warnings.push(`Valoración preliminar por moneda (ADR/FX, no se descarta la inversión): ${noComp.join(", ")}.`);
  if (noFv.length) warnings.push(`Sin Fair Value (abstención por valoración): ${noFv.join(", ")}.`);
  if (!scanAsOf) warnings.push("Fecha del scanner no disponible en esta carga.");
  warnings.push("Fair Value V1 es preliminar (DCF de FCFE con OCF−CAPEX aproximado); los modelos A/B experimentales NO se usan como señal.");

  const rules = [
    "Valoración ≠ elegibilidad: confiable / preliminar (FX, confianza) / vehículo (ETF por cartera) / sin datos. La ausencia de FX, score o Fair Value NO implica que la inversión no convenga.",
    `ACUMULAR (graduado): infravalorada ≥ +${pctS(MARGIN_UNDER)} con atractivo ≥ ${SCAN_WEAK}, o razonable con atractivo ≥ ${SCAN_ATTRACTIVE}. No exige que todos los indicadores sean favorables.`,
    `Margen > +${pctS(MARGIN_IMPLAUSIBLE)} ⇒ ALERTA de revisión (artefacto del DCF), no invalida otras señales ni genera compra.`,
    `Ruta ETF: se elige el ETF que más reduce la concentración efectiva (look-through) con menor exposición tecnológica; no exige Fair Value individual.`,
    "Restricciones duras (se mantienen): errores de datos, monedas incompatibles para comparar, peso/riesgo material por encima de tus límites.",
    "Se comparan A (aumentar) / B (nuevas) / C (ETF) / D (liquidez) y se elige la combinación más razonable; el 100% en efectivo es una decisión justificada, no un residuo.",
  ];
  const dataUsed = [
    `Posiciones reales (valor ${usd(V)}; ${holdings.length} instrumento(s)).`,
    "Fair Value: DCF de FCFE por empresa; exposición efectiva por X-Ray (look-through de ETF).",
    scanAsOf ? `Scanner del ${scanAsOf} (atractivo relativo).` : "Scanner: snapshot más reciente.",
    risk ? "Riesgo: covarianzas históricas (motor de Proyección)." : "Sin modelo de riesgo cargado.",
    `Límites: ${pctS(constraints.maxWeightAsset)} por activo, ${pctS(constraints.maxWeightSector)} por sector.`,
  ];

  recommendations.sort((a, b) => b.severity - a.severity);
  return {
    monthSummary, stance, portfolioValue: V, cash: cashInt, invested, cashKept,
    allocation, routes,
    before: { effN: beforeEffN, topWeight: topBeforeH?.weight ?? 0, topTicker: topBeforeH?.ticker ?? null },
    after: { effN: afterEffN, topWeight: topAfter?.w ?? 0, topTicker: topAfter?.t ?? null },
    cashNote, recommendations, opportunities, warnings, rules, dataUsed,
  };
}
