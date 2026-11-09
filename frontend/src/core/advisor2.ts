// Investment Advisor 2.0 — motor de recomendaciones DETERMINÍSTICO y valuation-aware.
// Integra, SIN confundir sus significados: Fair Value (margen de seguridad), calidad/actualidad
// de fundamentales, riesgo y concentración, exposición sectorial, proyección estadística y el
// score del scanner (atractivo relativo, NO alfa). Reglas transparentes con pesos razonados.
//
// PRINCIPIOS (del roadmap):
//  - Un ÚNICO DCF (Fair Value V1, preliminar) NO determina automáticamente COMPRAR ni VENDER.
//    Toda acción fuerte exige EVIDENCIA CONVERGENTE (margen + atractivo + calidad/riesgo).
//  - Los modelos A/B experimentales NO entran aquí (no se usan como señal).
//  - Sin datos suficientes ⇒ abstención (MANTENER/ESPERAR), nunca compra a ciegas.
//  - La suma de asignaciones = capital disponible EXACTAMENTE. Mantener efectivo es válido.

import type { Holding, Constraints, RiskModel } from "./advisor";
import { hhiFrom } from "./advisor";

export type Action2 = "COMPRAR" | "ACUMULAR" | "MANTENER" | "REDUCIR" | "VENDER" | "ESPERAR";

// Resumen de Fair Value por ticker (derivado de fairValueDCF en la página).
export interface FvSummary {
  available: boolean;
  priceComparable: boolean;
  marginBase: number | null;          // valor base / precio − 1
  marginConservative: number | null;
  marginOptimista: number | null;
  confidence: "Alta" | "Media" | "Baja" | null;
  currency: string | null;
  reason?: string;                    // si no disponible / no comparable
}
export interface ProjSummary { ret12mP50: number; ret12mP5: number; ret12mP95: number; annVol: number; }
export interface QualSummary { fresh: boolean; asOf: string | null; }

export interface Rec2 {
  ticker: string; name: string | null; action: Action2;
  why: string; evidence: string[]; risks: string[]; missing: string[];
  confidence: "alta" | "media" | "baja";
  marginLine: string; severity: number;
}
export interface Alloc2 {
  ticker: string; kind: "acumular" | "nueva"; amount: number; pctOfCash: number;
  newWeight: number; reason: string; marginLine: string;
}
export interface Opp2 {
  ticker: string; name: string | null; sector: string | null; composite: number;
  action: "COMPRAR" | "OBSERVAR" | "ESPERAR" | "INVESTIGAR";
  marginLine: string; note: string; eligible: boolean;
}
export interface Advisor2Report {
  monthSummary: string;
  stance: "desplegar" | "parcial" | "esperar";
  portfolioValue: number; cash: number; invested: number; cashKept: number;
  allocation: Alloc2[];
  before: { hhi: number; effN: number; topWeight: number; topTicker: string | null };
  after: { hhi: number; effN: number; topWeight: number; topTicker: string | null };
  recommendations: Rec2[];
  opportunities: Opp2[];
  warnings: string[];
  rules: string[];
  dataUsed: string[];
}

export interface Advisor2Input {
  holdings: Holding[];
  scan: { ticker: string; name?: string | null; sector: string | null; composite: number }[];
  cash: number;
  constraints: Constraints;
  fv: Record<string, FvSummary>;
  proj?: Record<string, ProjSummary>;
  qual?: Record<string, QualSummary>;
  risk?: RiskModel;
  scanAsOf?: string;
}

// Umbrales (documentados y mostrados en la UI).
const MARGIN_UNDER = 0.10;        // ≥ +10% ⇒ infravalorada
const MARGIN_STRONG_UNDER = 0.20; // ≥ +20% ⇒ muy infravalorada
const MARGIN_STRONG_OVER = -0.25; // ≤ −25% ⇒ muy sobrevalorada
const SCAN_STRONG = 65;
const SCAN_WEAK = 40;
const MAX_RISK = 0.45;
const STUB_W = 0.015;
const MAX_ALLOC_ITEMS = 5;

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
  const bucket = m >= MARGIN_STRONG_UNDER ? "muy infravalorada" : m >= MARGIN_UNDER ? "infravalorada"
    : m <= MARGIN_STRONG_OVER ? "muy sobrevalorada" : m <= -MARGIN_UNDER ? "sobrevalorada" : "en rango razonable";
  return `Margen de seguridad (base) ${m >= 0 ? "+" : ""}${pctS(m)} — ${bucket} (confianza ${s.confidence}).`;
}

// Redondeo a enteros que conserva EXACTAMENTE el total (mayor-resto).
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

// Reparto equitativo con tope por nombre (diversificación), redistribuye sobrante.
function waterfill(rooms: Map<string, number>, cash: number): Map<string, number> {
  const alloc = new Map<string, number>();
  for (const k of rooms.keys()) alloc.set(k, 0);
  let remaining = cash;
  let active = [...rooms.keys()].filter((k) => rooms.get(k)! > 1e-9);
  for (let guard = 0; guard < 200 && remaining > 1e-6 && active.length > 0; guard++) {
    const share = remaining / active.length;
    const next: string[] = [];
    let progressed = false;
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
  const { holdings, scan, cash, constraints, fv, proj, qual, risk, scanAsOf } = inp;
  const scanBy = new Map(scan.map((s) => [s.ticker.toUpperCase(), s]));
  const held = new Set(holdings.map((h) => h.ticker.toUpperCase()));
  const V = holdings.reduce((a, h) => a + (h.marketValue ?? 0), 0);
  const cashInt = Math.max(0, Math.round(cash));
  const riskBy = new Map((risk?.contrib ?? []).map((c) => [c.ticker.toUpperCase(), c.riskPct]));
  const denom = V + cashInt;
  const capPerAsset = constraints.maxWeightAsset * denom;

  // ───────────────────────── Recomendaciones por tenencia (cartera actual)
  const recommendations: Rec2[] = [];
  const accumulateCands: { ticker: string; current: number; composite: number }[] = [];

  for (const h of holdings) {
    const t = h.ticker.toUpperCase();
    const s = scanBy.get(t);
    const fvS = fv[t];
    const projS = proj?.[t];
    const q = qual?.[t];
    const riskPct = riskBy.get(t) ?? null;
    const mv = h.marketValue ?? 0;
    const overW = h.weight > constraints.maxWeightAsset;
    const highRisk = riskPct != null && riskPct > MAX_RISK;
    const mLine = marginLineOf(fvS);
    const valUsable = !!fvS && fvS.available && fvS.priceComparable && fvS.marginBase != null && (fvS.confidence === "Alta" || fvS.confidence === "Media");
    const m = valUsable ? fvS!.marginBase! : null;
    const composite = s?.composite ?? null;
    const knownStale = !!q && q.fresh === false;   // sólo bloquea si se sabe que NO es reciente
    const projLine = projS ? `Proyección 12m (estadística): mediana ${projS.ret12mP50 >= 0 ? "+" : ""}${pctS(projS.ret12mP50)}, rango ${pctS(projS.ret12mP5)}…+${pctS(projS.ret12mP95)}.` : null;
    const commonMissing: string[] = [];
    if (!fvS || !fvS.available) commonMissing.push("Fair Value no disponible (financiera o datos insuficientes).");
    else if (!fvS.priceComparable) commonMissing.push("Margen no comparable: precio y valor en distinta moneda (falta FX fechado).");
    if (q && !q.fresh) commonMissing.push(`Fundamentales no recientes (último ejercicio ${q.asOf ?? "s/f"}).`);
    if (!composite && composite !== 0) commonMissing.push("Sin score del scanner (fuera del universo evaluado).");

    // Vehículos (ETF/materia prima): sin valoración por empresa.
    if (isEtf(h.assetClass) || isCommodity(h.ticker, h.assetClass)) {
      const action: Action2 = overW || highRisk ? "REDUCIR" : "MANTENER";
      recommendations.push({
        ticker: h.ticker, name: h.name, action,
        why: action === "REDUCIR" ? `Recortar ${h.ticker}: concentración por encima de tu límite.` : `Mantener ${h.ticker}: cumple rol diversificador.`,
        evidence: [`Peso ${pctS(h.weight)}${riskPct != null ? `, ${pctS(riskPct)} del riesgo` : ""}.`,
          isCommodity(h.ticker, h.assetClass) ? "Materia prima: sin flujos; valor depende del spot." : "ETF: valoración look-through de subyacentes pendiente."],
        risks: action === "REDUCIR" ? ["Recortar reduce diversificación si es tu único vehículo amplio."] : ["Posible solapamiento con otras posiciones (ver X-Ray)."],
        missing: ["No aplica Fair Value por empresa a un vehículo diversificado."],
        confidence: "media", marginLine: "Vehículo diversificado — sin Fair Value por empresa.",
        severity: (action === "REDUCIR" ? 78 : 16) + h.weight * 40,
      });
      continue;
    }

    // Higiene: posición ínfima → VENDER.
    if (mv > 0 && h.weight < STUB_W) {
      recommendations.push({
        ticker: h.ticker, name: h.name, action: "VENDER",
        why: `Cerrar ${h.ticker}: posición demasiado pequeña (${pctS(h.weight)}) para mover la aguja.`,
        evidence: [`Peso ${pctS(h.weight)} (${usd(mv)}): añade complejidad sin impacto material.`, mLine],
        risks: ["Mantener es razonable si piensas construir la posición pronto."],
        missing: ["Decisión de higiene, no de valoración."],
        confidence: "media", marginLine: mLine, severity: 40,
      });
      continue;
    }

    // Gestión de RIESGO por concentración (independiente de valoración).
    if (overW || highRisk) {
      recommendations.push({
        ticker: h.ticker, name: h.name, action: "REDUCIR",
        why: `Recortar ${h.ticker}: ${overW ? `pesa ${pctS(h.weight)} (límite ${pctS(constraints.maxWeightAsset)})` : `concentra ${pctS(riskPct!)} del riesgo`}.`,
        evidence: [
          overW ? `Peso ${pctS(h.weight)} > límite ${pctS(constraints.maxWeightAsset)}.` : `Dentro del límite de peso, pero aporta ${pctS(riskPct!)} del riesgo (> ${pctS(MAX_RISK)}).`,
          mLine, projLine ?? "Proyección no disponible.",
        ].filter(Boolean),
        risks: ["Recortar un ganador reduce el recorrido si sigue subiendo; considera impuestos/costos.",
          valUsable && m! > MARGIN_UNDER ? "Parece infravalorada por Fair Value: el recorte es por riesgo, no porque esté cara." : ""].filter(Boolean),
        missing: commonMissing,
        confidence: highRisk ? "alta" : "media", marginLine: mLine,
        severity: (highRisk ? 90 : 82) + h.weight * 50,
      });
      continue;
    }

    // Valoración convergente (Fair Value usable + scanner + calidad).
    if (valUsable && m != null && composite != null) {
      // ACUMULAR: infravalorada Y atractivo no débil Y fundamentales recientes.
      if (m >= MARGIN_UNDER && composite >= SCAN_WEAK && !knownStale && mv < capPerAsset - 1e-6) {
        accumulateCands.push({ ticker: h.ticker, current: mv, composite });
        recommendations.push({
          ticker: h.ticker, name: h.name, action: "ACUMULAR",
          why: `Acumular ${h.ticker}: infravalorada (${m >= 0 ? "+" : ""}${pctS(m)}) y con atractivo relativo suficiente.`,
          evidence: [mLine, `Score ${Math.round(composite)}/100 (atractivo relativo, no alfa).`, knownStale ? "" : "Fundamentales recientes.", projLine ?? ""].filter(Boolean),
          risks: ["El Fair Value V1 es preliminar (DCF de FCFE aproximado); el margen puede estrecharse con mejores datos.",
            "El score es atractivo relativo, no una predicción de retorno."],
          missing: commonMissing,
          confidence: (fvS!.confidence === "Alta" && m >= MARGIN_STRONG_UNDER) ? "alta" : "media",
          marginLine: mLine, severity: 60 + Math.min(20, m * 40) + composite / 20,
        });
        continue;
      }
      // REDUCIR por valoración CONVERGENTE: muy sobrevalorada Y atractivo no fuerte.
      if (m <= MARGIN_STRONG_OVER && composite < SCAN_STRONG) {
        recommendations.push({
          ticker: h.ticker, name: h.name, action: "REDUCIR",
          why: `Recortar parcialmente ${h.ticker}: muy sobrevalorada (${pctS(m)}) y sin atractivo relativo fuerte.`,
          evidence: [mLine, `Score ${Math.round(composite)}/100 (< ${SCAN_STRONG}).`, projLine ?? ""].filter(Boolean),
          risks: ["El Fair Value V1 es preliminar: NO se vende la posición entera por un solo DCF; recorte parcial.",
            "Si el crecimiento supera tus supuestos, la sobrevaloración puede ser aparente."],
          missing: commonMissing,
          confidence: "media", marginLine: mLine, severity: 70 + Math.min(20, -m * 40),
        });
        continue;
      }
      // MANTENER con matiz (infravalorada-pero-débil, sobrevalorada-pero-fuerte, o en rango).
      const nuance = m >= MARGIN_UNDER ? "infravalorada pero atractivo relativo débil: no se fuerza compra por un solo DCF"
        : m <= -MARGIN_UNDER ? "parece algo cara pero momentum/calidad sostienen: no se vende por un solo DCF"
        : "precio en rango razonable del Fair Value";
      recommendations.push({
        ticker: h.ticker, name: h.name, action: "MANTENER",
        why: `Mantener ${h.ticker}: ${nuance}.`,
        evidence: [mLine, composite != null ? `Score ${Math.round(composite)}/100.` : "", projLine ?? "", `Peso ${pctS(h.weight)} dentro de límites.`].filter(Boolean),
        risks: ["El Fair Value V1 es preliminar; una señal aislada no basta para actuar."],
        missing: commonMissing,
        confidence: "media", marginLine: mLine, severity: 22 + h.weight * 20,
      });
      continue;
    }

    // Sin valoración usable → MANTENER prudente (sólo gestión de riesgo; sin compra a ciegas).
    recommendations.push({
      ticker: h.ticker, name: h.name, action: "MANTENER",
      why: `Mantener ${h.ticker}: sin valoración fundada hoy, sólo gestión de riesgo.`,
      evidence: [mLine, composite != null ? `Score ${Math.round(composite)}/100 (atractivo relativo).` : "Sin score.", projLine ?? "", `Peso ${pctS(h.weight)} dentro de límites.`].filter(Boolean),
      risks: ["Decidir sin Fair Value sube el riesgo de error: no se compra ni vende por valoración."],
      missing: commonMissing.length ? commonMissing : ["—"],
      confidence: "baja", marginLine: mLine, severity: 30 + h.weight * 20,
    });
  }

  // ───────────────────────── Oportunidades fuera de cartera
  const opportunities: Opp2[] = scan
    .filter((s) => !held.has(s.ticker.toUpperCase()) && s.composite >= SCAN_STRONG)
    .sort((a, b) => b.composite - a.composite)
    .slice(0, 8)
    .map((s) => {
      const t = s.ticker.toUpperCase();
      const fvS = fv[t];
      const mLine = marginLineOf(fvS);
      const usable = !!fvS && fvS.available && fvS.priceComparable && fvS.marginBase != null && (fvS.confidence === "Alta" || fvS.confidence === "Media");
      const m = usable ? fvS!.marginBase! : null;
      let action: Opp2["action"]; let note: string; let eligible = false;
      if (!fvS || !fvS.available || !usable) {
        action = "INVESTIGAR"; note = "Atractivo relativo alto, pero sin Fair Value comparable: no se compra sin valoración.";
      } else if (m! >= MARGIN_UNDER) {
        action = "COMPRAR"; eligible = true; note = `Atractivo alto e infravalorada (${m! >= 0 ? "+" : ""}${pctS(m!)}): candidata a desplegar capital.`;
      } else if (m! <= -MARGIN_UNDER) {
        action = "ESPERAR"; note = `Atractivo alto pero sobrevalorada (${pctS(m!)}): esperar mejor precio.`;
      } else {
        action = "OBSERVAR"; note = "Atractivo alto y precio en rango: en observación.";
      }
      return { ticker: s.ticker, name: s.name ?? null, sector: s.sector, composite: s.composite, action, marginLine: mLine, note, eligible };
    });

  // ───────────────────────── Asignación del aporte (exacta; efectivo permitido)
  const cands: { ticker: string; kind: "acumular" | "nueva"; current: number; composite: number }[] = [];
  for (const a of accumulateCands) cands.push({ ticker: a.ticker, kind: "acumular", current: a.current, composite: a.composite });
  for (const o of opportunities) if (o.eligible) cands.push({ ticker: o.ticker, kind: "nueva", current: 0, composite: o.composite });
  cands.sort((a, b) => b.composite - a.composite);
  const selected = cands.slice(0, MAX_ALLOC_ITEMS);

  let allocation: Alloc2[] = [];
  let invested = 0;
  if (cashInt > 0 && selected.length > 0) {
    const rooms = new Map<string, number>();
    for (const c of selected) rooms.set(c.ticker, Math.max(0, capPerAsset - c.current));
    const raw0 = waterfill(rooms, cashInt);
    const raw = selected.map((c) => ({ ticker: c.ticker, amount: raw0.get(c.ticker) ?? 0 })).filter((r) => r.amount > 0.5);
    const rounded = roundToBudget(raw, cashInt);
    invested = Object.values(rounded).reduce((a, b) => a + b, 0);
    allocation = selected.filter((c) => (rounded[c.ticker] ?? 0) > 0).map((c) => {
      const amt = rounded[c.ticker];
      const newVal = c.current + amt;
      const fvS = fv[c.ticker.toUpperCase()];
      return {
        ticker: c.ticker, kind: c.kind, amount: amt, pctOfCash: cashInt > 0 ? amt / cashInt : 0,
        newWeight: denom > 0 ? newVal / denom : 0,
        reason: c.kind === "acumular"
          ? "Infravalorada y atractiva: aumentar; monto por diversificación (partes iguales con tope por activo)."
          : "Candidata nueva infravalorada y atractiva: monto por diversificación con tope por activo.",
        marginLine: marginLineOf(fvS),
      };
    });
  }
  const cashKept = cashInt - invested;

  // Concentración antes/después
  const beforeW = holdings.filter((h) => h.marketValue).map((h) => h.weight);
  const beforeHhi = hhiFrom(beforeW);
  const topBeforeH = holdings.filter((h) => h.marketValue).sort((a, b) => b.weight - a.weight)[0] ?? null;
  const afterVals: Record<string, number> = {};
  for (const h of holdings) afterVals[h.ticker] = h.marketValue ?? 0;
  for (const it of allocation) afterVals[it.ticker] = (afterVals[it.ticker] ?? 0) + it.amount;
  const afterTotal = Object.values(afterVals).reduce((a, b) => a + b, 0) + cashKept;
  const afterEntries = Object.entries(afterVals).map(([t, v]) => ({ t, w: afterTotal > 0 ? v / afterTotal : 0 }));
  const afterHhi = hhiFrom(afterEntries.map((e) => e.w));
  const topAfter = [...afterEntries].sort((a, b) => b.w - a.w)[0] ?? null;

  // Resumen del mes + postura
  let stance: Advisor2Report["stance"]; let monthSummary: string;
  const strongActions = recommendations.filter((r) => r.action === "REDUCIR" || r.action === "VENDER");
  if (invested <= 0) {
    stance = "esperar";
    monthSummary = cashInt > 0
      ? `Mantener el aporte en liquidez: hoy ninguna posición ni candidata reúne evidencia convergente (margen + atractivo + calidad) para comprar.${strongActions.length ? ` Atención: ${strongActions.length} posición(es) a revisar por riesgo/valoración.` : ""}`
      : "Sin aporte a desplegar este mes; revisa las recomendaciones por posición.";
  } else {
    stance = cashKept > 0 ? "parcial" : "desplegar";
    monthSummary = `Desplegar ${usd(invested)} de ${usd(cashInt)} en ${allocation.length} instrumento(s) con evidencia convergente${cashKept > 0 ? `; mantener ${usd(cashKept)} en liquidez` : ""}. Concentración efectiva ${effN(beforeHhi).toFixed(1)}→${effN(afterHhi).toFixed(1)} posiciones.`;
  }

  // Avisos por datos incompletos
  const warnings: string[] = [];
  const noFv = holdings.filter((h) => !isEtf(h.assetClass) && !isCommodity(h.ticker, h.assetClass) && (!fv[h.ticker.toUpperCase()]?.available)).map((h) => h.ticker);
  const noComp = holdings.filter((h) => { const s = fv[h.ticker.toUpperCase()]; return s?.available && !s.priceComparable; }).map((h) => h.ticker);
  const noScan = holdings.filter((h) => h.marketValue != null && !scanBy.has(h.ticker.toUpperCase())).map((h) => h.ticker);
  const stale = holdings.filter((h) => qual?.[h.ticker.toUpperCase()]?.fresh === false).map((h) => h.ticker);
  if (noFv.length) warnings.push(`Sin Fair Value (no se decide por valoración): ${noFv.join(", ")}.`);
  if (noComp.length) warnings.push(`Margen no comparable por moneda (falta FX fechado): ${noComp.join(", ")}.`);
  if (noScan.length) warnings.push(`Fuera del universo del scanner: ${noScan.join(", ")}.`);
  if (stale.length) warnings.push(`Fundamentales no recientes: ${stale.join(", ")}.`);
  if (!scanAsOf) warnings.push("Fecha del scanner no disponible en esta carga.");
  warnings.push("Fair Value V1 es preliminar (DCF de FCFE aproximado); los modelos A/B experimentales NO se usan como señal.");

  const rules = [
    `Margen de seguridad: infravalorada ≥ +${pctS(MARGIN_UNDER)}, muy infravalorada ≥ +${pctS(MARGIN_STRONG_UNDER)}, muy sobrevalorada ≤ ${pctS(MARGIN_STRONG_OVER)}.`,
    `Atractivo (scanner): fuerte ≥ ${SCAN_STRONG}/100, débil < ${SCAN_WEAK}/100. Es atractivo relativo, no alfa.`,
    `ACUMULAR exige CONVERGENCIA: infravalorada + atractivo ≥ ${SCAN_WEAK} + fundamentales recientes + espacio bajo el tope por activo (${pctS(constraints.maxWeightAsset)}).`,
    `REDUCIR por valoración exige convergencia (muy sobrevalorada + atractivo < ${SCAN_STRONG}); nunca venta total por un solo DCF.`,
    `REDUCIR por riesgo: peso > ${pctS(constraints.maxWeightAsset)} o aporte al riesgo > ${pctS(MAX_RISK)} (independiente de valoración).`,
    "Sin Fair Value comparable o con confianza baja ⇒ abstención (MANTENER/INVESTIGAR). El efectivo es una opción válida.",
    "Monto por diversificación (partes iguales con tope por activo); el score filtra/ordena, NO dimensiona.",
  ];
  const dataUsed = [
    `Posiciones reales (valor ${usd(V)}; ${holdings.length} instrumento(s)).`,
    `Fair Value: DCF de FCFE (OCF−CAPEX aprox.) por empresa, margen vs. precio sólo si comparten moneda.`,
    scanAsOf ? `Scanner del ${scanAsOf} (atractivo relativo multifactor).` : "Scanner: snapshot más reciente.",
    risk ? "Riesgo: covarianzas históricas (motor de Proyección, precios ajustados)." : "Sin modelo de riesgo cargado.",
    `Límites: ${pctS(constraints.maxWeightAsset)} por activo, ${pctS(constraints.maxWeightSector)} por sector.`,
  ];

  recommendations.sort((a, b) => b.severity - a.severity);

  return {
    monthSummary, stance, portfolioValue: V, cash: cashInt, invested, cashKept,
    allocation,
    before: { hhi: beforeHhi, effN: effN(beforeHhi), topWeight: topBeforeH?.weight ?? 0, topTicker: topBeforeH?.ticker ?? null },
    after: { hhi: afterHhi, effN: effN(afterHhi), topWeight: topAfter?.w ?? 0, topTicker: topAfter?.t ?? null },
    recommendations, opportunities, warnings, rules, dataUsed,
  };
}
