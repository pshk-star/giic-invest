// Investment Advisor — motor DETERMINÍSTICO de apoyo a decisiones.
// Reglas transparentes y escenarios sobre datos REALES (posiciones, precios, scanner).
// NO inventa retornos esperados ni probabilidades: todo lo que afirma se deriva de
// cifras observables (pesos, concentración, score del scanner).
//
// IMPORTANTE (correcciones de diseño):
//  - El score del scanner es ATRACTIVO RELATIVO (percentil multifactor), NO una
//    predicción de retorno. Se usa solo para FILTRAR y RANKEAR candidatas, nunca para
//    dimensionar el monto (no se asume score alto = más retorno futuro).
//  - El monto se reparte por DIVERSIFICACIÓN (partes iguales con tope por activo),
//    no en proporción al score.
//  - El límite por activo se aplica al PESO RESULTANTE en la cartera total.
//  - Los ETF no se tratan como un sector económico.

export interface Holding {
  ticker: string;
  name: string | null;
  sector: string | null;
  assetClass: string | null;    // "equity" | "etf" | ... ; null si se desconoce
  marketValue: number | null;   // en USD; null si no hay precio
  weight: number;               // peso actual en la cartera (0-1)
  priceAsOf?: string | null;    // fecha del precio usado
}

export interface ScanInfo {
  ticker: string;
  name?: string | null;
  sector: string | null;
  composite: number;
  factors: { value: number; quality: number; growth: number; momentum: number; low_risk: number };
  tags: string[];
}

export interface Constraints {
  maxWeightAsset: number;   // p.ej. 0.25
  maxWeightSector: number;  // p.ej. 0.40
}

export interface Recommendation {
  kind: "reduce" | "trim_sector" | "hold_weak" | "add_existing" | "new_idea";
  ticker: string;
  conclusion: string;
  justification: string[];   // cifras concretas
  risks: string[];
  conditions: string[];      // qué cambiaría la recomendación
  composite?: number;
}

// Modelo de riesgo (opcional) proveniente del motor de Proyección (forecast.ts):
// contribución al riesgo por covarianzas, concentración efectiva y prob. de pérdida.
export interface RiskModel {
  annVol: number;
  effectiveN: number;
  hhi: number;
  probLoss12m: number;
  contrib: { ticker: string; weightPct: number; riskPct: number }[];
}

export type DecisionAction =
  | "COMPRAR" | "AUMENTAR" | "MANTENER" | "REDUCIR" | "VENDER" | "NO_HACER_NADA";

// Decisión priorizada y explicable (lo que el roadmap pide como entregable central).
export interface Decision {
  id: string;
  action: DecisionAction;
  ticker: string | null;          // null = decisión a nivel cartera
  label: string;                  // ticker o "Cartera"
  headline: string;               // conclusión en una línea
  priority: number;               // 1 = más importante
  severity: number;               // puntaje interno de orden (no se muestra)
  rationale: string[];            // cifras concretas que la respaldan
  metricNow: string;              // estado observado
  reference: string;              // umbral/base de comparación
  suggestedDeltaUsd: number | null;   // monto a mover (con signo); null si no aplica
  suggestedTargetWeight: number | null;
  expectedImpact: string;         // antes→después (peso/concentración/riesgo), sin inventar
  confidence: "alta" | "media" | "baja";
  whatWouldChange: string[];      // qué invalidaría o haría revisar la decisión
  dataSources: string[];
  limitations: string[];
}

export interface AllocationItem {
  ticker: string;
  kind: "add_existing" | "new_idea";
  amount: number;            // USD sugeridos (entero)
  newWeight: number;         // peso resultante en la cartera total
  composite: number;
  reason: string;
}

export interface AdvisorReport {
  portfolioValue: number;
  diagnostics: Recommendation[];
  ideas: Recommendation[];              // RANKING de oportunidades (separado de la asignación)
  allocation: {
    cash: number;
    invested: number;
    cashLeftover: number;
    items: AllocationItem[];
    method: string;                     // cómo se repartió el capital
    basisNote: string;                  // base del límite por activo (cartera total vs compra)
    before: { hhi: number; topWeight: number };
    after: { hhi: number; topWeight: number };
    note: string;
    blocked: string | null;             // si faltan restricciones esenciales, no damos montos
  };
  decisions: Decision[];                // 3-5 decisiones priorizadas con vocabulario completo
  compliance: { ok: boolean; remaining: string[] };   // incumplimientos que PERSISTEN tras la sugerencia
  alternatives: string[];               // mantener liquidez, ETF diversificado, etc.
  dataGaps: string[];                   // datos faltantes
  timing: string[];
  dataUsed: string[];
  constraints: Constraints;
}

const STRONG = 65;   // composite mínimo para considerar una candidata "atractiva"
const WEAK = 40;     // composite por debajo del cual una tenencia merece revisión
const MAX_ITEMS = 5; // nº máx. de candidatas en la asignación

function pctStr(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}
function usd(x: number): string {
  return `${Math.round(x).toLocaleString("en-US")} USD`;
}
function isEtf(assetClass: string | null | undefined): boolean {
  const a = (assetClass ?? "").toLowerCase();
  return a === "etf" || a === "fund" || a === "etn" || a === "mutualfund";
}

function hhiFrom(weights: number[]): number {
  const w = weights.filter((x) => x > 0);
  const s = w.reduce((a, b) => a + b, 0);
  if (s <= 0) return 0;
  return w.map((x) => x / s).reduce((a, b) => a + b * b, 0);
}

// Pesos por sector económico EXCLUYENDO ETF (un ETF no es un sector).
function sectorWeights(holdings: Holding[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const h of holdings) {
    if (!h.marketValue) continue;
    if (isEtf(h.assetClass)) continue;     // los ETF no computan como sector
    if (!h.sector) continue;               // sin sector clasificado -> no inventamos uno
    out[h.sector] = (out[h.sector] ?? 0) + h.weight;
  }
  return out;
}

// Reparto equitativo (diversificación) con tope por nombre; redistribuye el sobrante
// de los topados entre los no topados. Determinístico.
function waterfill(rooms: Map<string, number>, cash: number): Map<string, number> {
  const alloc = new Map<string, number>();
  for (const k of rooms.keys()) alloc.set(k, 0);
  let remaining = cash;
  let active = [...rooms.keys()].filter((k) => rooms.get(k)! > 1e-9);
  for (let guard = 0; guard < 200 && remaining > 1e-6 && active.length > 0; guard++) {
    const share = remaining / active.length;
    let progressed = false;
    const next: string[] = [];
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

// Redondeo a enteros que conserva EXACTAMENTE el total desplegado (mayor-resto).
function roundToBudget(raw: Array<{ ticker: string; kind: "add_existing" | "new_idea"; amount: number; current: number; composite: number }>):
  Array<{ ticker: string; kind: "add_existing" | "new_idea"; amount: number; current: number; composite: number }> {
  const target = Math.round(raw.reduce((a, r) => a + r.amount, 0));
  const parts = raw.map((r) => ({ ...r, floor: Math.floor(r.amount), frac: r.amount - Math.floor(r.amount) }));
  let used = parts.reduce((a, p) => a + p.floor, 0);
  let rem = target - used;
  parts.sort((a, b) => b.frac - a.frac);
  for (let i = 0; i < parts.length && rem > 0; i++) { parts[i].floor += 1; rem -= 1; }
  return parts.map((p) => ({ ticker: p.ticker, kind: p.kind, amount: p.floor, current: p.current, composite: p.composite }));
}

export function buildAdvice(
  holdings: Holding[],
  scan: ScanInfo[],
  cash: number,
  constraints: Constraints,
  scanAsOf?: string,
  risk?: RiskModel
): AdvisorReport {
  const scanBy = new Map(scan.map((s) => [s.ticker.toUpperCase(), s]));
  const held = new Set(holdings.map((h) => h.ticker.toUpperCase()));
  const V = holdings.reduce((a, h) => a + (h.marketValue ?? 0), 0);
  const secW = sectorWeights(holdings);
  const cashInt = Math.max(0, Math.round(cash));

  // ---------------------------------------------------------------- Diagnóstico
  const diagnostics: Recommendation[] = [];

  // Concentración por activo (sobre la cartera TOTAL actual).
  for (const h of holdings) {
    if (h.weight > constraints.maxWeightAsset && h.marketValue) {
      diagnostics.push({
        kind: "reduce", ticker: h.ticker,
        conclusion: `${h.ticker} supera tu límite por activo: evalúa recortar.`,
        justification: [
          `Peso actual ${pctStr(h.weight)} vs. límite ${pctStr(constraints.maxWeightAsset)} (sobre tu cartera total).`,
          `Valor de la posición: ${usd(h.marketValue)}.`,
          `Aportar capital a OTROS nombres diluye este peso, pero no lo baja por sí solo del límite.`,
        ],
        risks: ["Vender puede generar impuestos y costos; recortar un ganador reduce el upside si sigue subiendo."],
        conditions: [`Deja de aplicar si subes el límite por activo por encima de ${pctStr(h.weight)} o recortas la posición.`],
        composite: scanBy.get(h.ticker.toUpperCase())?.composite,
      });
    }
  }

  // Concentración por sector (ETF excluidos).
  for (const [sector, w] of Object.entries(secW)) {
    if (w > constraints.maxWeightSector) {
      diagnostics.push({
        kind: "trim_sector", ticker: sector,
        conclusion: `Sobreexposición al sector ${sector}: evalúa diversificar.`,
        justification: [`Peso del sector ${pctStr(w)} vs. límite ${pctStr(constraints.maxWeightSector)} (ETF no cuentan como sector).`],
        risks: ["Un shock sectorial te afecta desproporcionadamente."],
        conditions: [`Deja de aplicar si reduces el sector por debajo de ${pctStr(constraints.maxWeightSector)}.`],
      });
    }
  }

  // Tenencia con atractivo relativo bajo.
  for (const h of holdings) {
    const s = scanBy.get(h.ticker.toUpperCase());
    if (s && s.composite < WEAK && h.marketValue) {
      diagnostics.push({
        kind: "hold_weak", ticker: h.ticker,
        conclusion: `${h.ticker} tiene atractivo relativo bajo hoy: revísala.`,
        justification: [
          `Score multifactor ${Math.round(s.composite)}/100 (value ${Math.round(s.factors.value)}, quality ${Math.round(s.factors.quality)}, growth ${Math.round(s.factors.growth)}, momentum ${Math.round(s.factors.momentum)}).`,
        ],
        risks: ["El score es atractivo relativo, no una predicción; un score bajo no implica que caerá."],
        conditions: ["Reevalúa si mejora su score o cambian sus fundamentales."],
        composite: s.composite,
      });
    }
  }

  // ---------------------------------------------------------- Ranking de ideas
  // (SEPARADO de la asignación: esto es solo orden por atractivo relativo).
  const ideas: Recommendation[] = scan
    .filter((s) => !held.has(s.ticker.toUpperCase()) && s.composite >= STRONG)
    .sort((a, b) => b.composite - a.composite)
    .slice(0, 6)
    .map((s) => ({
      kind: "new_idea" as const, ticker: s.ticker, composite: s.composite,
      conclusion: `${s.ticker}${s.name ? " (" + s.name + ")" : ""}: candidata a investigar.`,
      justification: [
        `Score ${Math.round(s.composite)}/100 — value ${Math.round(s.factors.value)}, quality ${Math.round(s.factors.quality)}, growth ${Math.round(s.factors.growth)}, momentum ${Math.round(s.factors.momentum)}.`,
        `El score es atractivo relativo (percentil), NO una predicción de retorno.`,
        s.tags.length ? `Etiquetas: ${s.tags.join(", ")}.` : "Sin etiquetas destacadas.",
        s.sector ? `Sector ${s.sector}${(secW[s.sector] ?? 0) > constraints.maxWeightSector ? " — ya sobreexpuesto en tu cartera" : ""}.` : "",
      ].filter(Boolean),
      risks: ["No está en tu cartera: requiere investigar fundamentales y riesgos antes de comprar."],
      conditions: [`Deja de ser candidata si su score cae por debajo de ${STRONG} o rompe tu límite sectorial.`],
    }));

  // --------------------------------------------- Asignación determinística
  const denom = V + cashInt;
  const capPerAsset = constraints.maxWeightAsset * denom;  // tope de VALOR por activo tras invertir

  // Gate: sin capital válido no damos montos específicos (fix: evitar cantidades sin restricciones).
  let blocked: string | null = null;
  if (cashInt <= 0) {
    blocked = "Indica un capital a evaluar mayor que 0 para sugerir montos concretos.";
  }

  // Selección por RANKING (score), tamaño por DIVERSIFICACIÓN.
  type Cand = { ticker: string; kind: "add_existing" | "new_idea"; composite: number; current: number };
  const cands: Cand[] = [];
  for (const h of holdings) {
    const s = scanBy.get(h.ticker.toUpperCase());
    const cur = h.marketValue ?? 0;
    if (s && s.composite >= STRONG && cur < capPerAsset - 1e-6) {
      cands.push({ ticker: h.ticker, kind: "add_existing", composite: s.composite, current: cur });
    }
  }
  for (const s of scan) {
    if (held.has(s.ticker.toUpperCase())) continue;
    if (s.composite >= STRONG) cands.push({ ticker: s.ticker, kind: "new_idea", composite: s.composite, current: 0 });
  }
  cands.sort((a, b) => b.composite - a.composite);
  const selected = cands.slice(0, MAX_ITEMS);

  let items: AllocationItem[] = [];
  let invested = 0;
  let cashLeftover = cashInt;

  if (!blocked && selected.length > 0) {
    const rooms = new Map<string, number>();
    for (const c of selected) rooms.set(c.ticker, Math.max(0, capPerAsset - c.current));
    const alloc = waterfill(rooms, cashInt);
    const raw = selected
      .map((c) => ({ ticker: c.ticker, kind: c.kind, amount: alloc.get(c.ticker) ?? 0, current: c.current, composite: c.composite }))
      .filter((r) => r.amount > 0.5);
    const rounded = roundToBudget(raw);
    invested = rounded.reduce((a, r) => a + r.amount, 0);
    cashLeftover = cashInt - invested;   // invariante exacta: sum(items)+leftover = cash
    items = rounded.map((r) => {
      const newVal = r.current + r.amount;
      return {
        ticker: r.ticker, kind: r.kind, amount: r.amount,
        newWeight: denom > 0 ? newVal / denom : 0, composite: r.composite,
        reason: r.kind === "add_existing"
          ? `Aumentar: ya la tienes y su atractivo relativo es alto; monto por diversificación, no por score.`
          : `Nueva: atractivo relativo alto; monto por diversificación (partes iguales con tope por activo).`,
      };
    });
  }

  // ------------------------------------------------- Escenario antes/después
  const beforeWeights = holdings.filter((h) => h.marketValue).map((h) => h.weight);
  const afterVals: Record<string, number> = {};
  for (const h of holdings) afterVals[h.ticker] = h.marketValue ?? 0;
  for (const it of items) afterVals[it.ticker] = (afterVals[it.ticker] ?? 0) + it.amount;
  const afterTotal = Object.values(afterVals).reduce((a, b) => a + b, 0) + cashLeftover;
  const afterWeights = Object.values(afterVals).map((v) => (afterTotal > 0 ? v / afterTotal : 0));

  // ------------------------------------- Cumplimiento residual (fix: no mentir)
  const remaining: string[] = [];
  const afterSector: Record<string, number> = {};
  for (const h of holdings) {
    const val = afterVals[h.ticker] ?? 0;
    const w = afterTotal > 0 ? val / afterTotal : 0;
    if (w > constraints.maxWeightAsset + 1e-6) remaining.push(`${h.ticker} quedaría en ${pctStr(w)} (límite ${pctStr(constraints.maxWeightAsset)}).`);
    if (!isEtf(h.assetClass) && h.sector) afterSector[h.sector] = (afterSector[h.sector] ?? 0) + w;
  }
  // nuevas posiciones compradas (new_idea) también cuentan para el tope por activo
  for (const it of items) {
    if (it.kind === "new_idea") {
      const w = afterTotal > 0 ? it.amount / afterTotal : 0;
      if (w > constraints.maxWeightAsset + 1e-6) remaining.push(`${it.ticker} (nueva) quedaría en ${pctStr(w)} (límite ${pctStr(constraints.maxWeightAsset)}).`);
    }
  }
  for (const [sec, w] of Object.entries(afterSector)) {
    if (w > constraints.maxWeightSector + 1e-6) remaining.push(`Sector ${sec} quedaría en ${pctStr(w)} (límite ${pctStr(constraints.maxWeightSector)}).`);
  }
  const compliance = { ok: remaining.length === 0, remaining };

  // --------------------------------------------- Datos faltantes (fix: mostrarlos)
  const dataGaps: string[] = [];
  const noPrice = holdings.filter((h) => h.marketValue == null).map((h) => h.ticker);
  const noSector = holdings.filter((h) => !isEtf(h.assetClass) && !h.sector && h.marketValue != null).map((h) => h.ticker);
  const noScore = holdings.filter((h) => h.marketValue != null && !scanBy.has(h.ticker.toUpperCase())).map((h) => h.ticker);
  if (noPrice.length) dataGaps.push(`Sin precio (peso y valor aproximados): ${noPrice.join(", ")}.`);
  if (noSector.length) dataGaps.push(`Sin sector clasificado (no entran al chequeo sectorial): ${noSector.join(", ")}.`);
  if (noScore.length) dataGaps.push(`Sin score en el scanner (fuera del universo evaluado): ${noScore.join(", ")}.`);
  if (!scanAsOf) dataGaps.push("Fecha del scanner no disponible en esta carga.");

  // ------------------------------------------------- Alternativas (fix: liquidez/ETF)
  const alternatives: string[] = [];
  alternatives.push("Mantener en liquidez: consistente si ninguna candidata te convence o no quieres subir exposición ahora.");
  const topBefore = beforeWeights.length ? Math.max(...beforeWeights) : 0;
  const etfWeight = holdings.filter((h) => isEtf(h.assetClass) && h.marketValue).reduce((a, h) => a + h.weight, 0);
  if (topBefore > constraints.maxWeightAsset || (hhiFrom(beforeWeights) > 0.25 && etfWeight < 0.5)) {
    alternatives.push("Comprar un ETF diversificado de índice amplio: reduce concentración sin apostar a un solo nombre.");
  }
  if (Object.entries(secW).some(([, w]) => w > constraints.maxWeightSector)) {
    alternatives.push("Diversificar hacia un sector infrarrepresentado antes que reforzar el ya sobreexpuesto.");
  }
  if (remaining.length > 0) {
    alternatives.push("Reducir una exposición excesiva (recortar) es la única vía para bajar un peso ya por encima del límite; aportar capital nuevo no lo logra.");
  }

  // ---------------------------------------------------------------- Timing
  const timing: string[] = [
    cashInt > 0 && V > 0 && cashInt / denom > 0.15
      ? `El monto (${pctStr(cashInt / denom)} de tu cartera) es grande: escalonar en 2–3 tramos reduce el riesgo de entrada en un solo día.`
      : "Para montos pequeños relativos a tu cartera, un solo tramo suele bastar.",
    "Una candidata etiquetada 'oversold' admite un primer tramo mayor; una en 'momentum' favorece entrada escalonada. Son reglas observables, no pronósticos.",
    "Mantener parte en liquidez es válido si ninguna candidata supera tu umbral de score o romperías tus límites.",
  ];

  // ---------------------------------------------------------------- Datos usados
  const priceDates = holdings.map((h) => h.priceAsOf).filter((d): d is string => !!d).sort();
  const priceRange = priceDates.length
    ? (priceDates[0] === priceDates[priceDates.length - 1]
        ? `al ${priceDates[0]}`
        : `del ${priceDates[0]} al ${priceDates[priceDates.length - 1]}`)
    : "fecha no disponible";
  const dataUsed = [
    `Posiciones derivadas de tus operaciones (valor de mercado ${usd(V)}; ${holdings.length} instrumento(s), ${noPrice.length} sin precio).`,
    `Precios ${priceRange} (fuente: Yahoo Finance / Stooq vía el job diario).`,
    scanAsOf
      ? `Scanner del ${scanAsOf} — score multifactor (value, quality, growth, momentum, low-risk); atractivo relativo, no predicción.`
      : "Scanner: último snapshot disponible (fecha no cargada).",
    `Tus límites: ${pctStr(constraints.maxWeightAsset)} por activo, ${pctStr(constraints.maxWeightSector)} por sector.`,
  ];

  const note = blocked
    ? blocked
    : items.length === 0
      ? "Ninguna candidata cumple tus reglas hoy (score o límites): mantener liquidez es la opción consistente."
      : `Reparto determinístico por diversificación: ${usd(invested)} en partes equitativas (con tope por activo); ${usd(cashLeftover)} quedarían en liquidez.`;

  // ------------------------------------------ Decisiones priorizadas (3-5)
  const decisions = buildDecisions({
    holdings, constraints, cashInt, V, secW, scanBy, items,
    beforeHhi: hhiFrom(beforeWeights), afterHhi: hhiFrom(afterWeights),
    scanAsOf, risk,
  });

  return {
    portfolioValue: V,
    diagnostics,
    ideas,
    decisions,
    allocation: {
      cash: cashInt, invested, cashLeftover, items,
      method: "Partes iguales entre las candidatas seleccionadas por ranking, con tope por activo y redistribución del sobrante. El score filtra y ordena; NO dimensiona el monto.",
      basisNote: `El límite por activo se aplica al PESO RESULTANTE en tu cartera total. Tope por activo ≈ ${usd(capPerAsset)}.`,
      before: { hhi: hhiFrom(beforeWeights), topWeight: topBefore },
      after: { hhi: hhiFrom(afterWeights), topWeight: afterWeights.length ? Math.max(...afterWeights) : 0 },
      note,
      blocked,
    },
    compliance,
    alternatives,
    dataGaps,
    timing,
    dataUsed,
    constraints,
  };
}

const effN = (hhi: number): number => (hhi > 0 ? 1 / hhi : 0);

interface DecisionInput {
  holdings: Holding[];
  constraints: Constraints;
  cashInt: number;
  V: number;
  secW: Record<string, number>;
  scanBy: Map<string, ScanInfo>;
  items: AllocationItem[];
  beforeHhi: number;
  afterHhi: number;
  scanAsOf?: string;
  risk?: RiskModel;
}

// Sintetiza 3-5 decisiones priorizadas con el vocabulario completo. Determinístico.
// No inventa: cifras de peso/concentración son exactas; el riesgo (si hay modelo) es
// histórico por covarianzas; el score es atractivo relativo, nunca predicción.
function buildDecisions(inp: DecisionInput): Decision[] {
  const { holdings, constraints, cashInt, V, secW, scanBy, items, beforeHhi, afterHhi, scanAsOf, risk } = inp;
  const out: Decision[] = [];
  const riskBy = new Map((risk?.contrib ?? []).map((c) => [c.ticker.toUpperCase(), c]));
  const maxRiskPct = risk && risk.contrib.length ? Math.max(...risk.contrib.map((c) => c.riskPct)) : 0;
  const MAX_RISK = 0.45;
  const STUB_W = 0.015;
  const srcBase = [`Posiciones derivadas de tus operaciones (valor ${usd(V)}).`];
  const scanSrc = scanAsOf
    ? `Scanner del ${scanAsOf} (score multifactor = atractivo relativo, no predicción).`
    : "Scanner: snapshot más reciente.";
  const riskSrc = risk ? "Modelo de riesgo por covarianzas (motor de Proyección, histórico de precios ajustado)." : null;

  // 1) REDUCIR por concentración de PESO (autofinanciado a efectivo)
  for (const h of holdings) {
    if (!h.marketValue) continue;
    if (h.weight > constraints.maxWeightAsset) {
      const cap = constraints.maxWeightAsset;
      const delta = h.marketValue - cap * V;
      const after = holdings.map((x) => (x.ticker === h.ticker ? cap : (x.marketValue ?? 0) / V));
      after.push(h.weight - cap);
      const hhiA = hhiFrom(after);
      const rc = riskBy.get(h.ticker.toUpperCase());
      out.push({
        id: `red-${h.ticker}`, action: "REDUCIR", ticker: h.ticker, label: h.ticker,
        headline: `${h.ticker} pesa ${pctStr(h.weight)} — por encima de tu límite del ${pctStr(cap)}.`,
        priority: 0, severity: 100 + (h.weight - cap) * 100 + (rc && rc.riskPct > MAX_RISK ? 20 : 0),
        rationale: [
          `Peso ${pctStr(h.weight)} vs límite ${pctStr(cap)} (sobre tu cartera total).`,
          `Valor de la posición ${usd(h.marketValue)}.`,
          rc
            ? `Aporta ${pctStr(rc.riskPct)} del riesgo${rc.riskPct >= maxRiskPct ? " (la mayor de la cartera)" : ""}.`
            : `Sin modelo de riesgo cargado: el diagnóstico es por peso.`,
        ],
        metricNow: `Peso ${pctStr(h.weight)}${rc ? `, ${pctStr(rc.riskPct)} del riesgo` : ""}`,
        reference: `Límite por activo ${pctStr(cap)}`,
        suggestedDeltaUsd: -Math.round(delta), suggestedTargetWeight: cap,
        expectedImpact: `Recortar ${usd(delta)} lleva el peso a ${pctStr(cap)} y la concentración efectiva de ${effN(beforeHhi).toFixed(1)} a ${effN(hhiA).toFixed(1)} posiciones. Autofinanciado: el efectivo liberado queda disponible.`,
        confidence: rc ? (rc.riskPct > MAX_RISK ? "alta" : "media") : "media",
        whatWouldChange: [
          `Deja de aplicar si subes el límite por encima de ${pctStr(h.weight)} o si recortas la posición.`,
          "Recortar un ganador reduce el upside si sigue subiendo; considera impuestos y costos.",
        ],
        dataSources: riskSrc ? [...srcBase, riskSrc] : srcBase,
        limitations: [
          "El límite por activo es tuyo, no una ley de mercado.",
          rc ? "La contribución al riesgo es histórica (covarianzas), no predictiva." : "Sin modelo de riesgo: el impacto en riesgo no se cuantifica.",
        ],
      });
    }
  }

  // 2) REDUCIR por concentración de RIESGO (peso ok, riesgo dominante)
  if (risk) {
    for (const c of risk.contrib) {
      const h = holdings.find((x) => x.ticker.toUpperCase() === c.ticker.toUpperCase());
      if (!h || !h.marketValue) continue;
      if (h.weight <= constraints.maxWeightAsset && c.riskPct > MAX_RISK) {
        out.push({
          id: `redrisk-${c.ticker}`, action: "REDUCIR", ticker: c.ticker, label: c.ticker,
          headline: `${c.ticker} concentra ${pctStr(c.riskPct)} del riesgo pese a pesar solo ${pctStr(h.weight)}.`,
          priority: 0, severity: 90 + (c.riskPct - MAX_RISK) * 100,
          rationale: [
            `Contribución al riesgo ${pctStr(c.riskPct)} (> ${pctStr(MAX_RISK)}) por su volatilidad y correlaciones.`,
            `Peso ${pctStr(h.weight)} — dentro del límite, pero el riesgo no.`,
          ],
          metricNow: `${pctStr(c.riskPct)} del riesgo, peso ${pctStr(h.weight)}`,
          reference: `Umbral de riesgo por posición ${pctStr(MAX_RISK)}`,
          suggestedDeltaUsd: null, suggestedTargetWeight: null,
          expectedImpact: `Recortarla o diversificar hacia activos poco correlacionados baja la mayor fuente de varianza (concentración efectiva hoy ${effN(risk.hhi).toFixed(1)} posiciones).`,
          confidence: "media",
          whatWouldChange: ["Deja de aplicar si baja su volatilidad relativa o su correlación con el resto.", "Reevalúa si reduces la posición."],
          dataSources: riskSrc ? [...srcBase, riskSrc] : srcBase,
          limitations: ["La contribución al riesgo es histórica (covarianzas), no predictiva."],
        });
      }
    }
  }

  // 3) REDUCIR sector sobreexpuesto
  for (const [sec, w] of Object.entries(secW)) {
    if (w > constraints.maxWeightSector) {
      out.push({
        id: `sec-${sec}`, action: "REDUCIR", ticker: null, label: `Sector ${sec}`,
        headline: `Sobreexposición al sector ${sec}: ${pctStr(w)} (límite ${pctStr(constraints.maxWeightSector)}).`,
        priority: 0, severity: 80 + (w - constraints.maxWeightSector) * 100,
        rationale: [
          `Peso del sector ${pctStr(w)} vs límite ${pctStr(constraints.maxWeightSector)} (ETF no cuentan como sector).`,
          "Un shock sectorial te afecta de forma desproporcionada.",
        ],
        metricNow: `Sector ${pctStr(w)}`, reference: `Límite sectorial ${pctStr(constraints.maxWeightSector)}`,
        suggestedDeltaUsd: null, suggestedTargetWeight: null,
        expectedImpact: `Diversificar hacia un sector infrarrepresentado reduce el riesgo idiosincrático de ${sec}.`,
        confidence: "media",
        whatWouldChange: [`Deja de aplicar si reduces el sector por debajo de ${pctStr(constraints.maxWeightSector)}.`],
        dataSources: [...srcBase, "Clasificación sectorial SIC≈GICS (SEC)."],
        limitations: ["El sector usa SIC aproximado a GICS, no GICS oficial.", "Las posiciones sin sector clasificado no entran a este chequeo."],
      });
    }
  }

  // 4) COMPRAR / AUMENTAR (desplegar capital) — desde la asignación determinística
  if (cashInt > 0) {
    for (const it of items) {
      const isNew = it.kind === "new_idea";
      out.push({
        id: `buy-${it.ticker}`, action: isNew ? "COMPRAR" : "AUMENTAR", ticker: it.ticker, label: it.ticker,
        headline: `${isNew ? "Comprar" : "Aumentar"} ${it.ticker}: ${usd(it.amount)} (quedaría en ${pctStr(it.newWeight)}).`,
        priority: 0, severity: 55 + it.composite / 10,
        rationale: [
          `Atractivo relativo alto (score ${Math.round(it.composite)}/100).`,
          "Monto por diversificación (partes iguales con tope por activo), no por score.",
          isNew ? "No está en tu cartera: investiga fundamentales antes de comprar." : "Ya la tienes y hay espacio bajo tu tope por activo.",
        ],
        metricNow: `Score ${Math.round(it.composite)}/100`, reference: `Umbral de atractivo ${STRONG}/100`,
        suggestedDeltaUsd: it.amount, suggestedTargetWeight: it.newWeight,
        expectedImpact: afterHhi > 0 && beforeHhi > 0
          ? `Desplegar la asignación sube la concentración efectiva de ${effN(beforeHhi).toFixed(1)} a ${effN(afterHhi).toFixed(1)} posiciones.`
          : "Despliega capital hacia la candidata seleccionada.",
        confidence: scanAsOf ? "media" : "baja",
        whatWouldChange: [
          `Deja de aplicar si su score cae por debajo de ${STRONG} o rompe tu límite sectorial.`,
          "El score es atractivo relativo (percentil), no una predicción de retorno.",
        ],
        dataSources: [...srcBase, scanSrc],
        limitations: ["El score no predice retorno; el monto se dimensiona por diversificación.", isNew ? "Candidata aún no investigada a fondo." : ""].filter(Boolean),
      });
    }
  }

  // 5) VENDER posiciones ínfimas (higiene de cartera)
  for (const h of holdings) {
    if (!h.marketValue) continue;
    if (h.weight < STUB_W) {
      const s = scanBy.get(h.ticker.toUpperCase());
      out.push({
        id: `sell-${h.ticker}`, action: "VENDER", ticker: h.ticker, label: h.ticker,
        headline: `${h.ticker} pesa ${pctStr(h.weight)}: demasiado pequeña para mover la aguja.`,
        priority: 0, severity: 42,
        rationale: [
          `Peso ${pctStr(h.weight)} (${usd(h.marketValue)}): añade complejidad sin impacto material.`,
          s ? `Score ${Math.round(s.composite)}/100.` : "Sin score en el scanner.",
        ],
        metricNow: `Peso ${pctStr(h.weight)}`, reference: `Posición mínima relevante ${pctStr(STUB_W)}`,
        suggestedDeltaUsd: -Math.round(h.marketValue), suggestedTargetWeight: 0,
        expectedImpact: "Cerrarla simplifica la cartera; el efecto en riesgo/retorno es insignificante por su tamaño.",
        confidence: "media",
        whatWouldChange: ["Mantener es razonable si piensas construir la posición pronto.", "Considera costos e impuestos de la venta."],
        dataSources: srcBase, limitations: ["Decisión de higiene de cartera, no una señal de valoración."],
      });
    }
  }

  out.sort((a, b) => b.severity - a.severity);
  const top = out.slice(0, 5);

  // 6) MANTENER: si queda cupo, destaca una posición núcleo bien comportada
  if (top.length < 5) {
    const flagged = new Set(top.filter((d) => d.ticker).map((d) => d.ticker!.toUpperCase()));
    const core = holdings
      .filter((h) => h.marketValue && h.weight >= 0.08 && h.weight <= constraints.maxWeightAsset && !flagged.has(h.ticker.toUpperCase()))
      .sort((a, b) => (b.marketValue ?? 0) - (a.marketValue ?? 0))[0];
    if (core) {
      const s = scanBy.get(core.ticker.toUpperCase());
      top.push({
        id: `hold-${core.ticker}`, action: "MANTENER", ticker: core.ticker, label: core.ticker,
        headline: `Mantener ${core.ticker}: núcleo dentro de tus límites.`,
        priority: 0, severity: 20,
        rationale: [
          `Peso ${pctStr(core.weight)} — dentro del límite del ${pctStr(constraints.maxWeightAsset)}.`,
          s ? `Score ${Math.round(s.composite)}/100 (atractivo relativo).` : "Dentro de límites por peso (sin score).",
        ],
        metricNow: `Peso ${pctStr(core.weight)}`, reference: `Límite por activo ${pctStr(constraints.maxWeightAsset)}`,
        suggestedDeltaUsd: null, suggestedTargetWeight: null,
        expectedImpact: "Ninguno: no requiere acción hoy.",
        confidence: "media",
        whatWouldChange: ["Revísala si su peso supera el límite o su atractivo relativo cae.", "Un cambio de fundamentales cambia la tesis."],
        dataSources: scanAsOf ? [...srcBase, scanSrc] : srcBase,
        limitations: ["'Mantener' no es garantía de desempeño futuro."],
      });
    }
  }

  // 7) NO HACER NADA: si no hubo nada accionable
  if (top.length === 0) {
    top.push({
      id: "noop", action: "NO_HACER_NADA", ticker: null, label: "Cartera",
      headline: "Hoy no hay una acción que mejore tu cartera de forma clara.",
      priority: 1, severity: 0,
      rationale: [
        "Ninguna posición supera tus límites de concentración por activo o sector.",
        cashInt > 0 ? "Ninguna candidata del scanner supera tu umbral de atractivo con tus reglas." : "No indicaste capital nuevo a desplegar.",
      ],
      metricNow: risk
        ? `Concentración efectiva ${risk.effectiveN.toFixed(1)} posiciones; prob. de pérdida a 12m ${pctStr(risk.probLoss12m)}.`
        : "Dentro de tus límites.",
      reference: `Límites ${pctStr(constraints.maxWeightAsset)} por activo, ${pctStr(constraints.maxWeightSector)} por sector`,
      suggestedDeltaUsd: null, suggestedTargetWeight: null,
      expectedImpact: "Sin cambios: esperar es consistente con tus reglas.",
      confidence: "media",
      whatWouldChange: [
        "Aparecerá una acción si una posición rompe un límite, si subes el capital a desplegar, o si cambian los scores.",
        "Puedes probar escenarios en «Proyección».",
      ],
      dataSources: scanAsOf ? [...srcBase, scanSrc] : srcBase,
      limitations: ["Ausencia de acción no significa ausencia de riesgo."],
    });
  }

  return top.map((d, i) => ({ ...d, priority: i + 1 }));
}

export { hhiFrom };
