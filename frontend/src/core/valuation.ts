// Valoración relativa y lectura de fundamentales — DETERMINÍSTICO y transparente.
// Todos los supuestos son explícitos y editables; NADA se inventa. Donde falta un dato,
// la función devuelve null y la UI lo marca como "no disponible". Estos modelos son
// APROXIMACIONES con datos gratuitos (EDGAR), no consensos de analistas.

export interface FundamentalsPayload {
  pe_ttm: number | null;
  eps?: number | null;            // EPS reportado (USD/ADR) → rendimiento de beneficios no circular
  eps_basis?: string | null;      // reported_annual | ttm | normalized | forward
  eps_consistent?: boolean | null; // identidad EPS×acciones≈utilidad neta
  eps_check_ratio?: number | null; // EPS×acciones / utilidad neta (≈1 si coherente)
  ni_reconstructed?: boolean;     // utilidad neta reconstruida de EPS×acciones (etiqueta directa ausente)
  ni_source_concept?: string | null;  // concepto EDGAR de la utilidad neta (o "reconstruido: ...")
  ni_period?: string | null;      // período fiscal de la utilidad neta
  consistency_independent?: boolean;  // true sólo si la consistencia usó NI reportado (no reconstruido)
  eps_source?: string | null;     // edgar | yahoo:quote | ...
  fallback_sources?: string | null;  // campos tomados de fallback y su origen/fecha
  shares_source?: string | null;  // procedencia de las acciones vigentes

  pe_forward: number | null;      // no disponible gratis (EDGAR) -> null
  ev_ebitda: number | null;       // no disponible gratis -> null
  fcf_yield: number | null;       // FCF / market cap
  roic: number | null;            // no disponible gratis -> null
  roe: number | null;
  rev_growth_yoy: number | null;
  eps_growth_yoy: number | null;
  net_margin: number | null;
  debt_to_equity: number | null;
  market_cap: number | null;
  currency?: string | null;       // divisa de reporte (EDGAR): USD, EUR, TWD, ...
  as_of?: string | null;          // fin del último ejercicio anual usado (YYYY-MM-DD)
  taxonomy?: string | null;       // us-gaap | ifrs-full (procedencia)

  // Campos EDGAR adicionales ya persistidos (dataclass → payload):
  eps_annual?: number | null;     // EPS diluido anual (USD/ADR)
  eps_ttm?: number | null;        // EPS diluido TTM
  fcf_annual?: number | null;     // FCF anual (OCF − CAPEX)
  fcf_ttm?: number | null;        // FCF TTM
  net_debt?: number | null;       // deuda neta (divisa de reporte)
  gross_debt?: number | null;     // deuda bruta
  cash_and_sti?: number | null;   // caja + inversiones de corto plazo
  operating_margin?: number | null;
  gross_margin?: number | null;
  diluted_shares?: number | null; // acciones diluidas ponderadas (solo EDGAR)

  source_kind?: string | null;    // 'eodhd_primary' si no hay ancla SEC
  enrichment?: EnrichmentBlock | null;
  history?: HistoryBlock | null;
}

// Campo enriquecido (EODHD) con procedencia, período y calidad — NO confundir elegible con verificado.
export interface EnrichedField {
  value: number | null;
  currency?: string | null;
  source?: string | null;
  symbol?: string | null;
  period_end?: string | null;
  period_type?: string | null;    // anual | ttm | trimestre_individual | ytd_acumulado | balance_instantaneo | indeterminado
  quality_state?: string | null;  // verificado | parcial | desactualizado | inconsistente | faltante
  usable_recency?: boolean;
  valuation_eligible?: boolean;
  valuation_note?: string | null;
}

export interface EnrichmentBlock {
  schema_version?: string;
  generated_at?: string;
  source?: string;
  symbol?: string | null;
  currency?: string | null;
  edgar_data_end?: string | null;
  valuation_eligible_meaning?: string;
  source_kind?: string;
  carried_forward?: boolean;
  fields?: Record<string, EnrichedField>;
  quarantine?: Record<string, EnrichedField>;
}

export interface HistoryRecord {
  period_end: string;
  revenue: number | null; net_income: number | null; operating_income: number | null;
  ocf: number | null; capex: number | null; fcf: number | null;
  cash: number | null; gross_debt: number | null; net_debt: number | null;
  op_margin: number | null; net_margin: number | null;
}

export interface HistoryBlock {
  source?: string;
  currency?: string | null;
  annual?: HistoryRecord[];
}

export function median(xs: Array<number | null | undefined>): number | null {
  const v = xs.filter((x): x is number => typeof x === "number" && isFinite(x)).sort((a, b) => a - b);
  if (v.length === 0) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

export function peerMedian(peers: FundamentalsPayload[], key: keyof FundamentalsPayload,
                           positiveOnly = true): number | null {
  const xs = peers.map((p) => p[key]).filter((x): x is number =>
    typeof x === "number" && isFinite(x) && (!positiveOnly || x > 0));
  return median(xs);
}

export interface FairValue {
  method: string;
  assumption: string;
  upsidePct: number;        // (valor estimado / precio actual) - 1
  note: string;
}

// Valor relativo por P/E: lleva el P/E de la empresa a la mediana del sector.
// fairPrice = price * (peerPE / companyPE)  ->  upside = peerPE/companyPE - 1
export function fairValueByPE(companyPE: number | null, peerPE: number | null): FairValue | null {
  if (!companyPE || !peerPE || companyPE <= 0 || peerPE <= 0) return null;
  return {
    method: "Comparables (P/E ttm)",
    assumption: `P/E objetivo = mediana del sector = ${peerPE.toFixed(1)}× (editable).`,
    upsidePct: peerPE / companyPE - 1,
    note: "Aproximación por múltiplos; supone que la empresa debería cotizar al P/E mediano de sus pares.",
  };
}

// Valor relativo por FCF yield: lleva el FCF yield de la empresa a la mediana del sector.
// A mayor yield, más barata. fairPrice = price * (companyYield / peerYield).
export function fairValueByFcfYield(companyYield: number | null, peerYield: number | null): FairValue | null {
  if (!companyYield || !peerYield || companyYield <= 0 || peerYield <= 0) return null;
  return {
    method: "Comparables (FCF yield)",
    assumption: `FCF yield objetivo = mediana del sector = ${(peerYield * 100).toFixed(1)}% (editable).`,
    upsidePct: companyYield / peerYield - 1,
    note: "Aproximación; supone que la empresa debería ofrecer el FCF yield mediano de sus pares.",
  };
}

// Lectura inversa (Gordon de FCF, perpetuidad): con un retorno requerido r y el FCF yield
// actual, el crecimiento de FCF IMPLÍCITO en el precio es g ≈ r − fcf_yield.
export function impliedFcfGrowth(fcfYield: number | null, requiredReturn: number): number | null {
  if (fcfYield === null || !isFinite(fcfYield) || fcfYield <= 0) return null;
  return requiredReturn - fcfYield;
}

// Explicación en lenguaje llano de cada factor (percentil 0-100 del universo).
export function factorExplanation(name: string, v: number | null): string {
  if (v === null || !isFinite(v)) return "Sin dato.";
  const p = Math.round(v);
  switch (name) {
    case "value":    return `Percentil ${p}: ${p >= 50 ? "más barata" : "más cara"} que el ${p >= 50 ? p : 100 - p}% del universo por múltiplos.`;
    case "quality":  return `Percentil ${p}: rentabilidad/solidez (ROE, margen) ${p >= 50 ? "por encima" : "por debajo"} de la media del universo.`;
    case "growth":   return `Percentil ${p}: crecimiento de ingresos/EPS ${p >= 50 ? "superior" : "inferior"} al ${p >= 50 ? p : 100 - p}% del universo.`;
    case "momentum": return `Percentil ${p}: tendencia de precio (6–12m) ${p >= 50 ? "fuerte" : "débil"} relativa al universo. Observable, no predicción.`;
    case "low_risk": return `Percentil ${p}: volatilidad ${p >= 50 ? "baja" : "alta"} relativa (mayor percentil = menos volátil).`;
    default:         return `Percentil ${p}.`;
  }
}

export interface ScanFactors {
  composite: number;
  value: number | null; quality: number | null; growth: number | null;
  momentum: number | null; low_risk: number | null;
  tags: string[];
}

// Riesgos determinísticos a partir de cifras observables (no especulación).
export function riskFlags(f: FundamentalsPayload, peerPE: number | null, scan: ScanFactors | null): string[] {
  const out: string[] = [];
  if (f.pe_ttm && peerPE && f.pe_ttm > peerPE * 1.2)
    out.push(`Cotiza con prima vs. sector: P/E ${f.pe_ttm.toFixed(1)}× sobre mediana ${peerPE.toFixed(1)}×.`);
  if (f.debt_to_equity && f.debt_to_equity > 2)
    out.push(`Apalancamiento alto: deuda/capital ${f.debt_to_equity.toFixed(1)}×.`);
  if (f.rev_growth_yoy !== null && f.rev_growth_yoy < 0)
    out.push(`Ingresos en contracción: ${(f.rev_growth_yoy * 100).toFixed(1)}% interanual.`);
  if (scan) {
    if (scan.composite < 50) out.push(`Atractivo relativo bajo: score ${Math.round(scan.composite)}/100 (percentil, no predicción).`);
    if (scan.momentum !== null && scan.momentum < 30) out.push(`Momentum débil (percentil ${Math.round(scan.momentum)}).`);
    if (scan.tags.includes("value_trap")) out.push("Posible value trap: barata pero con deterioro.");
  }
  return out;
}

// ───────────────────────────── Fair Value V1 — DCF (FCFE, determinístico) ─────────────────────────────
// Convención FINANCIERAMENTE CONSISTENTE: FCFE → coste de EQUITY → equity DIRECTAMENTE.
// El flujo FCF = OCF − CAPEX ya es POST-intereses y POST-impuestos (OCF incluye intereses pagados
// y el impuesto en efectivo), por lo que es un FCFE (flujo al accionista) con endeudamiento neto ≈ 0.
// Se descuenta al coste de EQUITY (Ke = rf + β·ERP) y la suma de VP ES el valor del equity:
//   Equity = Σ VP(FCFE) + VP(terminal);  valor/acción = Equity / acciones diluidas.
// NO se resta la deuda neta (su servicio ya está dentro del FCFE vía OCF): restarla sería doble conteo.
// La caja/deuda neta se muestra como memo informativo, no se suma (evita doble conteo del interés
// ya reflejado en OCF). No se mezcla FCFF con FCFE. Si faltan datos fiables ⇒ {available:false}.

export interface DcfAssumptions {
  years: number;        // horizonte explícito
  g1: number;           // crecimiento de FCFE del primer año
  gTerminal: number;    // crecimiento terminal (conservador, < tasa)
  discount: number;     // coste de EQUITY (Ke), no WACC
}
export interface DcfRun {
  pvExplicit: number; pvTerminal: number;
  equity: number; perShare: number; terminalWeight: number;
}
// DCF de FCFE determinístico. El crecimiento decae linealmente de g1 a gTerminal durante el horizonte.
// La suma de valores presentes ES el equity (sin ajuste de deuda neta: ya está en el FCFE).
export function runDcf(baseFcf: number, shares: number, a: DcfAssumptions): DcfRun | null {
  if (!(baseFcf > 0) || !(shares > 0) || !(a.discount > a.gTerminal) || a.years < 1) return null;
  let pv = 0, fcf = baseFcf;
  for (let t = 1; t <= a.years; t++) {
    const g = a.g1 + (a.gTerminal - a.g1) * (t - 1) / Math.max(1, a.years - 1);
    fcf = fcf * (1 + g);
    pv += fcf / Math.pow(1 + a.discount, t);
  }
  const tv = (fcf * (1 + a.gTerminal)) / (a.discount - a.gTerminal);
  const pvTerminal = tv / Math.pow(1 + a.discount, a.years);
  const equity = pv + pvTerminal;           // FCFE descontado a Ke ⇒ equity directamente
  return { pvExplicit: pv, pvTerminal, equity, perShare: equity / shares, terminalWeight: pvTerminal / equity };
}

export interface DcfScenario { name: string; a: DcfAssumptions; run: DcfRun; marginVsPrice: number | null; }
export interface DcfInputs {
  baseFcf: number; baseFcfMethod: string; lastFcf: number | null;
  netDebt: number; netDebtKnown: boolean; shares: number; currency: string;
  histYears: number; baseGrowth: number;
}
export interface SensitivityCell { discount: number; gTerminal: number; perShare: number | null; }
export interface FairValueDCF {
  available: boolean; reason?: string;
  inputs?: DcfInputs;
  scenarios?: DcfScenario[];        // [conservador, base, optimista]
  base?: DcfScenario;
  sensitivity?: SensitivityCell[];  // rejilla tasa × crecimiento terminal (escenario base)
  impliedGrowth?: number | null;    // crecimiento de FCF implícito en el precio (DCF inverso)
  priceComparable?: boolean;        // precio en misma moneda que el valor intrínseco
  confidence?: "Alta" | "Media" | "Baja";
  confidenceNotes?: string[];
}

// Base FCF NORMALIZADO: margen FCF medio (últimos ≤4 años) × ingresos del último ejercicio.
// Suaviza la volatilidad de CAPEX sin descartar la escala actual. Alternativa: mediana de FCF.
function normalizedBaseFcf(hist: HistoryRecord[]): { base: number | null; method: string; lastFcf: number | null } {
  const rows = hist.filter((h) => typeof h.fcf === "number" && isFinite(h.fcf as number));
  if (rows.length < 3) return { base: null, method: "insuficiente", lastFcf: rows.length ? rows[rows.length - 1].fcf! : null };
  const lastFcf = rows[rows.length - 1].fcf!;
  const withRev = rows.filter((h) => typeof h.revenue === "number" && (h.revenue as number) > 0);
  const recent = withRev.slice(-4);
  if (recent.length >= 3) {
    const margins = recent.map((h) => (h.fcf as number) / (h.revenue as number));
    const avgMargin = margins.reduce((s, m) => s + m, 0) / margins.length;
    const lastRev = withRev[withRev.length - 1].revenue as number;
    return { base: lastRev * avgMargin, method: `margen FCF medio ${(avgMargin * 100).toFixed(1)}% × ingresos`, lastFcf };
  }
  const last3 = rows.slice(-3).map((h) => h.fcf as number).sort((a, b) => a - b);
  return { base: last3[1], method: "mediana FCF 3 años", lastFcf };
}

// Crecimiento base de referencia: CAGR de ingresos (≤5 años), acotado [0, 18%].
function revenueCagr(hist: HistoryRecord[]): number {
  const rows = hist.filter((h) => typeof h.revenue === "number" && (h.revenue as number) > 0).slice(-6);
  if (rows.length < 2) return 0.05;
  const first = rows[0].revenue as number, last = rows[rows.length - 1].revenue as number, n = rows.length - 1;
  if (first <= 0 || last <= 0) return 0.05;
  return Math.min(0.18, Math.max(0, Math.pow(last / first, 1 / n) - 1));
}

const RF = 0.04, ERP = 0.05, BETA = 1.1;        // supuestos de tasa (editables, documentados)
export const DISCOUNT_BASE = RF + BETA * ERP;   // 9.5% coste de EQUITY (Ke) base

// DCF inverso: crecimiento de FCFE constante implícito en el precio (equity objetivo), por bisección.
function impliedGrowthFor(targetEquity: number, baseFcf: number, shares: number,
                          discount: number, gTerminal: number, years: number): number | null {
  if (!(baseFcf > 0) || !(shares > 0) || targetEquity <= 0) return null;
  const equityAt = (g: number) => {
    const r = runDcf(baseFcf, shares, { years, g1: g, gTerminal, discount });
    return r ? r.equity : null;
  };
  // g1 (tramo explícito) puede superar la tasa de descuento; sólo gTerminal<tasa importa.
  let lo = -0.15, hi = 0.60;
  const eLo = equityAt(lo), eHi = equityAt(hi);
  if (eLo === null || eHi === null) return null;
  if (targetEquity <= eLo) return lo;
  if (targetEquity >= eHi) return hi;
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2, e = equityAt(mid);
    if (e === null) return null;
    if (e < targetEquity) lo = mid; else hi = mid;
  }
  return (lo + hi) / 2;
}

// Punto de entrada: construye inputs, 3 escenarios, sensibilidad, DCF inverso y confianza.
export function fairValueDCF(fund: FundamentalsPayload, price: number | null, priceCcy: string | null): FairValueDCF {
  const hist = (fund.history?.annual ?? []).filter((h) => h && h.period_end) as HistoryRecord[];
  const ccy = fund.history?.currency ?? fund.currency ?? "USD";
  const nb = normalizedBaseFcf(hist);
  const shares = typeof fund.diluted_shares === "number" && fund.diluted_shares > 0 ? fund.diluted_shares : null;

  if (nb.base === null)
    return { available: false, reason: "Sin FCF histórico suficiente (≥3 años anuales). El DCF industrial no aplica — probable entidad financiera o datos insuficientes." };
  if (nb.base <= 0)
    return { available: false, reason: "FCF base normalizado no positivo: un DCF forzaría un valor no defendible. Valoración no disponible." };
  if (shares === null)
    return { available: false, reason: "Acciones diluidas no disponibles: no es posible convertir a valor por acción." };

  const netDebt = typeof fund.net_debt === "number" && isFinite(fund.net_debt) ? fund.net_debt
    : (hist.length && typeof hist[hist.length - 1].net_debt === "number" ? hist[hist.length - 1].net_debt as number : 0);
  const netDebtKnown = typeof fund.net_debt === "number" || (hist.length > 0 && typeof hist[hist.length - 1].net_debt === "number");
  const baseG = revenueCagr(hist);
  const inputs: DcfInputs = {
    baseFcf: nb.base, baseFcfMethod: nb.method, lastFcf: nb.lastFcf,
    netDebt, netDebtKnown, shares, currency: ccy, histYears: hist.length, baseGrowth: baseG,
  };

  const priceComparable = price != null && price > 0 && !!priceCcy && priceCcy.toUpperCase() === ccy.toUpperCase();
  const mcap = priceComparable ? price! * shares : null;    // equity de mercado en moneda de reporte

  const defs: Array<{ name: string; g1: number; gT: number; disc: number }> = [
    { name: "Conservador", g1: Math.max(0, baseG * 0.5), gT: 0.020, disc: DISCOUNT_BASE + 0.010 },
    { name: "Base",        g1: baseG,                      gT: 0.025, disc: DISCOUNT_BASE },
    { name: "Optimista",   g1: Math.min(0.25, baseG * 1.3 + 0.02), gT: 0.030, disc: DISCOUNT_BASE - 0.010 },
  ];
  const scenarios: DcfScenario[] = [];
  for (const d of defs) {
    const a: DcfAssumptions = { years: 10, g1: d.g1, gTerminal: d.gT, discount: d.disc };
    const run = runDcf(nb.base, shares, a);
    if (!run) continue;
    const marginVsPrice = mcap != null ? run.equity / mcap - 1 : null;
    scenarios.push({ name: d.name, a, run, marginVsPrice });
  }
  if (scenarios.length < 3)
    return { available: false, reason: "No fue posible construir el DCF con supuestos consistentes (tasa ≤ crecimiento terminal)." };
  const base = scenarios[1];

  // Sensibilidad: tasa (±1pp) × crecimiento terminal (±0.5pp) sobre el escenario base.
  const sensitivity: SensitivityCell[] = [];
  for (const dd of [-0.01, 0, 0.01]) for (const dg of [-0.005, 0, 0.005]) {
    const a: DcfAssumptions = { years: 10, g1: base.a.g1, gTerminal: base.a.gTerminal + dg, discount: base.a.discount + dd };
    const r = runDcf(nb.base, shares, a);
    sensitivity.push({ discount: a.discount, gTerminal: a.gTerminal, perShare: r ? r.perShare : null });
  }

  const impliedGrowth = mcap != null
    ? impliedGrowthFor(mcap, nb.base, shares, base.a.discount, base.a.gTerminal, 10) : null;

  // Confianza
  const notes: string[] = [];
  let score = 0;
  if (hist.length < 5) { score += 1; notes.push(`Solo ${hist.length} años de histórico FCF.`); }
  const fcfs = hist.map((h) => h.fcf).filter((x): x is number => typeof x === "number");
  const mean = fcfs.reduce((s, x) => s + x, 0) / Math.max(1, fcfs.length);
  const cv = mean > 0 ? Math.sqrt(fcfs.reduce((s, x) => s + (x - mean) ** 2, 0) / fcfs.length) / mean : 1;
  if (cv > 0.5) { score += 1; notes.push(`FCF volátil (CV ${cv.toFixed(2)}): base normalizada sensible al año.`); }
  // FCFE asume endeudamiento neto ≈ 0: si la deuda neta es material vs. equity, el supuesto es más débil.
  if (netDebtKnown && netDebt > 0 && base.run.equity > 0 && netDebt / base.run.equity > 0.3) {
    score += 1; notes.push(`Deuda neta ${(netDebt / base.run.equity * 100).toFixed(0)}% del equity: el FCFE supone endeudamiento neto ≈ 0 (supuesto más débil).`);
  }
  if (base.run.terminalWeight > 0.75) { score += 1; notes.push(`${(base.run.terminalWeight * 100).toFixed(0)}% del valor procede del valor terminal.`); }
  notes.push(`Caja/deuda neta (${inputs.netDebtKnown ? "memo" : "n/d"}) no se suma al equity: su servicio ya está en el FCFE (evita doble conteo).`);
  if (!priceComparable) notes.push(`Precio en ${priceCcy ?? "s/d"} y valor en ${ccy}: margen vs. precio requiere FX fechado (no calculado).`);
  const confidence: "Alta" | "Media" | "Baja" = score >= 3 ? "Baja" : score >= 1 ? "Media" : "Alta";

  return { available: true, inputs, scenarios, base, sensitivity, impliedGrowth, priceComparable, confidence, confidenceNotes: notes };
}

// Datos faltantes, nombrados explícitamente.
export function missingFundamentals(f: FundamentalsPayload): string[] {
  const labels: Array<[keyof FundamentalsPayload, string]> = [
    ["pe_ttm", "P/E ttm"], ["pe_forward", "P/E forward"], ["ev_ebitda", "EV/EBITDA"],
    ["fcf_yield", "FCF yield"], ["roic", "ROIC"], ["roe", "ROE"],
    ["rev_growth_yoy", "Crec. ingresos"], ["eps_growth_yoy", "Crec. EPS"],
    ["net_margin", "Margen neto"], ["debt_to_equity", "Deuda/Capital"], ["market_cap", "Market cap"],
  ];
  return labels.filter(([k]) => f[k] === null || f[k] === undefined).map(([, l]) => l);
}
