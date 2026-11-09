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
