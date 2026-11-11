// P2.2 — Opportunity Scanner (EXPERIMENTAL, bajo feature flag). Motor PURO y testeable.
// Compara oportunidades DENTRO y FUERA de la cartera sobre el universo que GIIC ya monitorea.
// Responde: ¿qué alternativas merecen capital nuevo frente a aumentar posiciones, comprar ETF o
// mantener efectivo? NO ejecuta operaciones, NO reemplaza decisiones de Advisor 3.0: lo ALIMENTA
// con candidatos. REUTILIZA los criterios/controles de Advisor 3.0 (sin duplicar lógica de decisión):
//  - solo el FV PRODUCTIVO con confianza suficiente habilita accionabilidad por valor;
//  - el FCFF experimental NO es fuente principal; un margen positivo por sí solo NO basta;
//  - datos faltantes REDUCEN confianza / impiden accionabilidad, nunca inflan el score.
// Tres clasificaciones SEPARADAS (no un score único opaco): fundamental, diversificación, accionable.
import {
  effectiveMargin, modelDisagreement, isEtf, passesValueGate, sufficient, ADV3_THRESHOLDS,
  type Adv3Valuation, type Adv3Constraints, type Adv3Position, type Conf,
} from "./advisor3";
import { riskContributions, concentration } from "./portfolio-risk";

export type InstrumentKind = "empresa" | "etf" | "banco" | "otro";

export interface ScanCandidate {
  ticker: string; name?: string | null; sector?: string | null; country?: string | null;
  currency?: string | null; assetClass?: string | null; kind: InstrumentKind;
  inPortfolio: boolean; composite?: number | null;   // score cuantitativo del scanner (CONTEXTO, no gatillo)
}
export interface ScanFundamentals {
  roic?: number | null; revGrowth?: number | null; netMargin?: number | null;
  operatingMargin?: number | null; fcfTtm?: number | null;
}
export interface ScanPortfolio { positions: Adv3Position[]; cash: number }
export interface ScanInput {
  candidates: ScanCandidate[];
  valuation: Record<string, Adv3Valuation>;
  fundamentals: Record<string, ScanFundamentals>;
  portfolio: ScanPortfolio;
  priceHistory: Record<string, { as_of: string; close: number }[]>;  // cartera + candidatos (para riesgo marginal)
  etfLookthrough?: Record<string, Record<string, number>>;           // etf -> {ticker: peso 0..1} (exposición duplicada)
  contributions?: number[];                                          // por defecto [1000, 3000]
  constraints: Adv3Constraints;
}

export interface SimPoint {
  amount: number;
  weightBefore: number; weightAfter: number;
  volBefore: number; volAfter: number; deltaVol: number;
  marginalRiskContribPct: number | null;    // contribución del candidato al riesgo de la cartera resultante
  hhiSectorBefore: number; hhiSectorAfter: number; deltaHhiSector: number;  // >0 = reduce concentración
  duplicatedExposure: number;                // fracción de la cartera ya expuesta al nombre vía ETF
  totalBefore: number; totalAfter: number;   // conservación: totalAfter == totalBefore + amount
  cashBefore: number; cashIfFunded: number; exceedsCash: boolean;  // impacto sobre efectivo si se financia con caja
}

export type ScanClassification = "no_evaluable" | "evaluable_no_atractivo" | "atractivo_no_accionable" | "accionable";

export interface ScanEntry {
  ticker: string; name?: string | null; sector?: string | null; kind: InstrumentKind; inPortfolio: boolean;
  margin: number | null; marginSource: string; confidence: Conf; disagreement: "direccional" | "magnitud" | null;
  quality: ScanFundamentals;
  fundamentalScore: number | null;
  diversificationScore: number | null;
  actionable: boolean; actionableBasis: "valor" | "diversificador" | null;
  eligible: boolean;                 // tipo valorable por fundamentales (empresa/banco)
  classification: ScanClassification;
  blockedByProductiveVeto: boolean;  // FCFF lo haría atractivo pero el FV productivo (antiguo) lo impide
  reasons: string[]; missing: string[]; whatWouldChange: string[];
  sims: SimPoint[];
}
export interface ScanRanking { id: "fundamental" | "diversificacion" | "accionable"; label: string; entries: ScanEntry[]; note: string }
export interface ScanCoverage {
  total: number; evaluated: number; excluded: number; eligibleCompanies: number;
  withAnyValuation: number; withProductiveFv: number; withFcff: number; withFundamentals: number; withReturns: number;
  classification: Record<ScanClassification, number>;
  blockedByProductiveVeto: { count: number; tickers: string[] };
}
export interface ScannerReport {
  asOf: string;
  universeSize: number; evaluated: number;
  portfolioValue: number; cash: number;
  baseVol: number; baseHhiSector: number; hasConcentrationProblem: boolean;
  coverage: ScanCoverage;
  entries: ScanEntry[];
  rankings: ScanRanking[];
  excluded: { ticker: string; reason: string }[];
  dataProvenance: string[];
  guardrails: string[];
}

// Alinea precios → retornos diarios sobre las fechas COMUNES a los tickers pedidos. Determinista.
function alignReturns(priceHistory: Record<string, { as_of: string; close: number }[]>, tickers: string[]): Record<string, number[]> {
  const maps: Record<string, Map<string, number>> = {};
  const keyLists: string[][] = [];
  for (const t of tickers) {
    const bars = priceHistory[t];
    if (!bars || bars.length < 2) continue;
    const m = new Map<string, number>(bars.map((b) => [b.as_of, b.close] as [string, number]));
    maps[t] = m; keyLists.push(Array.from(m.keys()));
  }
  if (!keyLists.length) return {};
  let dates = keyLists[0];
  for (let i = 1; i < keyLists.length; i++) { const s = new Set<string>(keyLists[i]); dates = dates.filter((d) => s.has(d)); }
  dates = [...dates].sort();
  const out: Record<string, number[]> = {};
  for (const t of Object.keys(maps)) {
    const px = dates.map((d) => maps[t].get(d) ?? 0);
    out[t] = px.slice(1).map((p, i) => (px[i] > 0 ? p / px[i] - 1 : 0));
  }
  return out;
}

export function buildScanner(inp: ScanInput, asOf = new Date().toISOString().slice(0, 10)): ScannerReport {
  const { candidates, valuation, fundamentals, portfolio, priceHistory, etfLookthrough, constraints } = inp;
  const contributions = (inp.contributions && inp.contributions.length ? inp.contributions : [1000, 3000]).slice().sort((a, b) => a - b);
  const { UNDER, RISK_TRIM, DIVERSIFY_MIN } = ADV3_THRESHOLDS;
  const minMargin = constraints.minMarginToBuy ?? UNDER;

  const positions = portfolio.positions;
  const cash = portfolio.cash;
  const totalInvested = positions.reduce((s, p) => s + p.marketValue, 0);
  const portfolioValue = totalInvested + cash;
  const meta: Record<string, { sector?: string; country?: string; currency?: string }> = {};
  for (const p of positions) meta[p.ticker] = { sector: p.sector ?? "na", country: p.country ?? "na", currency: p.currency ?? "USD" };

  const baseWeights: Record<string, number> = {};
  for (const p of positions) baseWeights[p.ticker] = portfolioValue > 0 ? p.marketValue / portfolioValue : 0;
  const baseReturns = alignReturns(priceHistory, positions.map((p) => p.ticker));
  const baseRc = riskContributions(baseWeights, baseReturns);
  const baseConc = concentration(baseWeights, meta, "sector");
  const baseVol = baseRc.volPortfolioAnnual;
  const baseHhi = baseConc.hhi;

  const hasConcProblem = Object.entries(baseRc.byPosition).some(([, c]) => c.contribPct > RISK_TRIM)
    || Object.values(baseConc.byGroup).some((w) => w > constraints.maxSectorWeight);

  // exposición económica ya presente vía ETF en cartera (look-through)
  function duplicatedExposure(ticker: string): number {
    if (!etfLookthrough) return 0;
    let dup = 0;
    for (const p of positions) {
      const lt = etfLookthrough[p.ticker];
      if (!lt) continue;
      const wEtf = baseWeights[p.ticker] ?? 0;
      dup += wEtf * (lt[ticker] ?? 0);
    }
    return Number(dup.toFixed(4));
  }

  // Alinea retornos UNA vez por candidato (no depende del monto): clave para no degradar el rendimiento
  // al evaluar el universo completo sin tope (P2.3, punto 8).
  function candidateReturns(c: ScanCandidate): Record<string, number[]> {
    const inPos = positions.some((p) => p.ticker === c.ticker);
    const tk = inPos ? positions.map((p) => p.ticker) : [...positions.map((p) => p.ticker), c.ticker];
    return alignReturns(priceHistory, tk);
  }

  function simulate(c: ScanCandidate, amount: number, simReturns: Record<string, number[]>): SimPoint {
    const inPos = positions.find((p) => p.ticker === c.ticker);
    const mvBefore = inPos?.marketValue ?? 0;
    const totalAfter = portfolioValue + amount;
    // pesos nuevos sobre la cartera resultante (capital nuevo). El candidato puede ser nombre nuevo.
    const nw: Record<string, number> = {};
    const nmeta: Record<string, { sector?: string; country?: string; currency?: string }> = { ...meta };
    for (const p of positions) nw[p.ticker] = (p.marketValue + (p.ticker === c.ticker ? amount : 0)) / totalAfter;
    if (!inPos) { nw[c.ticker] = amount / totalAfter; nmeta[c.ticker] = { sector: c.sector ?? "na", country: c.country ?? "na", currency: c.currency ?? "USD" }; }
    const afterRc = riskContributions(nw, simReturns);
    const afterConc = concentration(nw, nmeta, "sector");
    const marginal = afterRc.byPosition[c.ticker]?.contribPct ?? null;
    return {
      amount,
      weightBefore: Number((portfolioValue > 0 ? mvBefore / portfolioValue : 0).toFixed(4)),
      weightAfter: Number((nw[c.ticker] ?? 0).toFixed(4)),
      volBefore: Number(baseVol.toFixed(4)), volAfter: Number(afterRc.volPortfolioAnnual.toFixed(4)),
      deltaVol: Number((afterRc.volPortfolioAnnual - baseVol).toFixed(4)),
      marginalRiskContribPct: marginal == null ? null : Number(marginal.toFixed(4)),
      hhiSectorBefore: Number(baseHhi.toFixed(4)), hhiSectorAfter: Number(afterConc.hhi.toFixed(4)),
      deltaHhiSector: Number((baseHhi - afterConc.hhi).toFixed(5)),
      duplicatedExposure: duplicatedExposure(c.ticker),
      totalBefore: portfolioValue, totalAfter,
      cashBefore: cash, cashIfFunded: cash - amount, exceedsCash: amount > cash,
    };
  }

  const entries: ScanEntry[] = [];
  const excluded: { ticker: string; reason: string }[] = [];
  const cov = { withAnyValuation: 0, withProductiveFv: 0, withFcff: 0, withFundamentals: 0, withReturns: 0, eligibleCompanies: 0 };
  const blockedTickers: string[] = [];

  for (const c of candidates) {
    const val = valuation[c.ticker];
    const em = effectiveMargin(val);
    const dis = modelDisagreement(val);
    const f = fundamentals[c.ticker] ?? {};
    const hasReturns = !!priceHistory[c.ticker] && priceHistory[c.ticker].length >= 2;
    const reasons: string[] = []; const missing: string[] = []; const whatWouldChange: string[] = [];

    // cobertura (sobre TODO el universo, antes de excluir)
    const hasProd = val?.productiveMargin != null;
    const hasFcff = val?.fcffMargin != null;
    const hasFund = f.roic != null || f.revGrowth != null || f.netMargin != null;
    const eligible = c.kind === "empresa" || c.kind === "banco";
    if (hasProd) cov.withProductiveFv++;
    if (hasFcff) cov.withFcff++;
    if (hasProd || hasFcff) cov.withAnyValuation++;
    if (hasFund) cov.withFundamentals++;
    if (hasReturns) cov.withReturns++;
    if (eligible) cov.eligibleCompanies++;

    // candidato sin NINGÚN dato utilizable: ni valoración ni historial → excluido (no se inventa score)
    if (em.margin == null && !hasReturns && c.kind !== "etf") {
      excluded.push({ ticker: c.ticker, reason: "sin valoración ni historial de precios: no clasificable" });
      continue;
    }

    const simReturns = candidateReturns(c);
    const sims = contributions.map((a) => simulate(c, a, simReturns));
    const simMax = sims[sims.length - 1];

    // confianza: parte de la valoración; se DEGRADA si faltan fundamentales
    let confidence: Conf = em.conf;
    const fundMissing = f.roic == null && f.revGrowth == null && f.netMargin == null;
    if (fundMissing) { if (confidence === "alta") confidence = "media"; else if (confidence === "media") confidence = "baja"; missing.push("sin ROIC/crecimiento/margen"); }
    if (!hasReturns) { missing.push("sin historial de precios para riesgo marginal"); }

    // (A) score FUNDAMENTAL: SOLO empresas con FV productivo. El FCFF no sustituye. Calidad inclina, no infla.
    let fundamentalScore: number | null = null;
    if (c.kind === "empresa" || c.kind === "banco") {
      if (em.source === "productivo" && em.margin != null) {
        let tilt = 0;
        if (f.roic != null) tilt += f.roic >= 0.15 ? 0.03 : f.roic < 0.05 ? -0.03 : 0;
        if (f.revGrowth != null) tilt += f.revGrowth > 0.10 ? 0.02 : f.revGrowth < 0 ? -0.03 : 0;
        if (f.netMargin != null) tilt += f.netMargin > 0.15 ? 0.02 : f.netMargin < 0 ? -0.03 : 0;
        fundamentalScore = Number((em.margin + tilt).toFixed(4));
        reasons.push(`FV productivo: margen ${(em.margin * 100).toFixed(0)}% (confianza ${confidence}).` + (tilt ? ` Calidad inclina ${tilt > 0 ? "+" : ""}${(tilt * 100).toFixed(0)} pp.` : ""));
        if (em.note.includes("FCFF")) reasons.push("FCFF experimental corrobora (contexto, no fuente principal).");
      } else {
        missing.push("sin FV productivo comparable");
        whatWouldChange.push("un FV productivo con confianza suficiente lo haría clasificable por fundamentales y accionable.");
      }
    } else {
      reasons.push("Vehículo (ETF/otro): no se valora por DCF/FCFF; se evalúa por rol en la cartera.");
    }

    // (B) score DIVERSIFICACIÓN: reducción de concentración sectorial (no requiere FV). Se muestra qué
    // se sacrifica (deltaVol): menor vol NO implica automáticamente mejor inversión.
    const diversificationScore = simMax ? Number(simMax.deltaHhiSector.toFixed(5)) : null;
    if (diversificationScore != null && diversificationScore > 0) {
      reasons.push(`Diversifica: reduce HHI sector en ${diversificationScore} con $${simMax.amount} (Δvol ${(simMax.deltaVol * 100).toFixed(2)} pp).`);
    }

    // (C) ACCIONABLE: reutiliza los controles de Advisor 3.0. Empresa por VALOR; ETF por DIVERSIFICACIÓN.
    let actionable = false; let actionableBasis: "valor" | "diversificador" | null = null;
    if (c.kind === "empresa" || c.kind === "banco") {
      if (passesValueGate(val, minMargin) && !dis.material && simMax && simMax.weightAfter <= constraints.maxPositionWeight) {
        actionable = true; actionableBasis = "valor";
        reasons.push("Accionable por VALOR: FV productivo con margen+confianza suficientes, sin desacuerdo material, respeta tope de peso.");
      } else if (dis.material) {
        whatWouldChange.push(`Desacuerdo de modelos (${dis.kind}): convergencia lo volvería accionable.`);
      }
    } else if (isEtf(c.assetClass) || c.kind === "etf") {
      if (hasConcProblem && simMax && simMax.deltaHhiSector >= DIVERSIFY_MIN) {
        actionable = true; actionableBasis = "diversificador";
        reasons.push("Accionable como DIVERSIFICADOR: la cartera está concentrada y este ETF reduce el HHI de forma material.");
      }
    }

    if (dis.material) reasons.push(`Desacuerdo de modelos (${dis.kind}, brecha ${((dis.gap ?? 0) * 100).toFixed(0)} pp): confianza degradada.`);
    if (!actionable && c.kind !== "etf" && em.margin != null && em.margin > 0 && !passesValueGate(val, minMargin)) {
      reasons.push("Margen positivo pero NO accionable: no supera margen+confianza del FV productivo (no se compra solo por margen).");
    }
    whatWouldChange.push(fundMissing ? "fundamentales (ROIC/crecimiento/margen) elevarían la confianza." : "un cambio de margen o convergencia de modelos movería la clasificación.");

    // Bloqueado SOLO por el DCF productivo (antiguo): el FCFF lo haría atractivo, pero el FV productivo
    // falta, es poco atractivo o discrepa direccionalmente. NO se cambia la regla aquí: es el insumo de P2.4.
    const fcffAttractive = val?.fcffMargin != null && val.fcffMargin >= minMargin && sufficient(val?.fcffConfidence ?? null);
    const usableProd = em.source === "productivo" && em.margin != null;
    const blockedByProductiveVeto = eligible && !actionable && !!fcffAttractive
      && (!usableProd || (em.margin != null && em.margin < minMargin) || dis.kind === "direccional");
    if (blockedByProductiveVeto) { blockedTickers.push(c.ticker); reasons.push("BLOQUEADO solo por el DCF productivo: el FCFF lo haría atractivo; sin cambiar la regla (insumo de P2.4)."); }

    // Clasificación de 4 vías
    const attractiveByProd = passesValueGate(val, minMargin);
    let classification: ScanClassification;
    if (eligible) {
      classification = actionable ? "accionable"
        : (attractiveByProd || blockedByProductiveVeto) ? "atractivo_no_accionable" : "evaluable_no_atractivo";
    } else {
      classification = actionable ? "accionable" : (hasReturns ? "evaluable_no_atractivo" : "no_evaluable");
    }

    entries.push({
      ticker: c.ticker, name: c.name, sector: c.sector, kind: c.kind, inPortfolio: c.inPortfolio,
      margin: em.margin, marginSource: em.source, confidence, disagreement: dis.kind,
      quality: { roic: f.roic ?? null, revGrowth: f.revGrowth ?? null, netMargin: f.netMargin ?? null, operatingMargin: f.operatingMargin ?? null, fcfTtm: f.fcfTtm ?? null },
      fundamentalScore, diversificationScore, actionable, actionableBasis,
      eligible, classification, blockedByProductiveVeto,
      reasons, missing, whatWouldChange, sims,
    });
  }

  // Orden determinista/reproducible: por score desc, desempate por ticker asc.
  const byScore = (get: (e: ScanEntry) => number | null) => (a: ScanEntry, b: ScanEntry) => {
    const av = get(a) ?? -Infinity, bv = get(b) ?? -Infinity;
    return bv !== av ? bv - av : a.ticker.localeCompare(b.ticker);
  };

  const fundamental = entries.filter((e) => e.fundamentalScore != null).sort(byScore((e) => e.fundamentalScore));
  const diversificacion = entries.filter((e) => e.diversificationScore != null && e.diversificationScore > 0).sort(byScore((e) => e.diversificationScore));
  const accionable = entries.filter((e) => e.actionable).sort((a, b) => {
    // valor primero (por margen), luego diversificadores (por reducción de HHI); nunca un score mezclado
    const rank = (e: ScanEntry) => e.actionableBasis === "valor" ? 0 : 1;
    if (rank(a) !== rank(b)) return rank(a) - rank(b);
    const key = a.actionableBasis === "valor" ? (e: ScanEntry) => e.fundamentalScore : (e: ScanEntry) => e.diversificationScore;
    const av = key(a) ?? -Infinity, bv = key(b) ?? -Infinity;
    return bv !== av ? bv - av : a.ticker.localeCompare(b.ticker);
  });

  const rankings: ScanRanking[] = [
    { id: "fundamental", label: "A · Oportunidades fundamentales", entries: fundamental,
      note: "Solo empresas con FV productivo; el FCFF corrobora, no sustituye. La calidad inclina el score, los datos faltantes reducen la confianza." },
    { id: "diversificacion", label: "B · Oportunidades de diversificación", entries: diversificacion,
      note: "Ordenadas por reducción de concentración (HHI sector). Menor volatilidad NO implica mejor inversión: se muestra el Δvol y qué se sacrifica." },
    { id: "accionable", label: "C · Oportunidades accionables", entries: accionable,
      note: "Pasan los controles de Advisor 3.0: empresas por VALOR (FV productivo + confianza, sin desacuerdo material) y ETF por DIVERSIFICACIÓN. Datos insuficientes = no accionable." },
  ];

  const classCounts: Record<ScanClassification, number> = { no_evaluable: excluded.length, evaluable_no_atractivo: 0, atractivo_no_accionable: 0, accionable: 0 };
  for (const e of entries) classCounts[e.classification]++;
  const coverage: ScanCoverage = {
    total: candidates.length, evaluated: entries.length, excluded: excluded.length, eligibleCompanies: cov.eligibleCompanies,
    withAnyValuation: cov.withAnyValuation, withProductiveFv: cov.withProductiveFv, withFcff: cov.withFcff,
    withFundamentals: cov.withFundamentals, withReturns: cov.withReturns,
    classification: classCounts,
    blockedByProductiveVeto: { count: blockedTickers.length, tickers: blockedTickers.slice().sort() },
  };

  return {
    asOf,
    universeSize: candidates.length, evaluated: entries.length,
    portfolioValue, cash,
    baseVol: Number(baseVol.toFixed(4)), baseHhiSector: Number(baseHhi.toFixed(4)), hasConcentrationProblem: hasConcProblem,
    coverage,
    entries, rankings, excluded,
    dataProvenance: [
      "universo: v_latest_scan (scanner cuantitativo) ∪ cartera ∪ ETF",
      "valoración: FV productivo + FCFF experimental (P1.9, pit_snapshots)",
      "fundamentales: tabla fundamentals (ROIC/crecimiento/márgenes)",
      "riesgo: retornos históricos (price_history), paridad Python",
      "exposición duplicada: look-through de ETF (X-ray)",
    ],
    guardrails: [
      "El scanner ALIMENTA Advisor 3.0 con candidatos; no ejecuta operaciones ni reemplaza decisiones.",
      "Solo el FV productivo con confianza suficiente habilita accionabilidad por valor; el FCFF no es fuente principal.",
      "Un margen positivo por sí solo NO es señal de compra.",
      "Datos faltantes reducen la confianza o impiden la clasificación accionable; nunca inflan el score.",
      "No se inventan retornos esperados; la diversificación se mide por concentración/riesgo observados.",
      "Tres clasificaciones separadas (fundamental/diversificación/accionable); sin score único opaco.",
    ],
  };
}
