// Investment Advisor — motor DETERMINÍSTICO de apoyo a decisiones (Fase D inicial).
// Reglas transparentes y análisis de escenarios sobre datos REALES (posiciones,
// precios, scanner). NO inventa retornos esperados ni probabilidades: todo lo que
// afirma se deriva de cifras observables (pesos, concentración, score del scanner).
//
// El score del scanner es ATRACTIVO RELATIVO (percentil multifactor), no una
// predicción. El advisor lo usa como un insumo más, siempre explicando el porqué.

export interface Holding {
  ticker: string;
  name: string | null;
  sector: string | null;
  marketValue: number | null;   // en USD; null si no hay precio
  weight: number;               // peso actual en la cartera (0-1)
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

export interface AllocationItem {
  ticker: string;
  kind: "add_existing" | "new_idea";
  amount: number;            // USD sugeridos
  newWeight: number;         // peso tras la compra
  composite: number;
  reason: string;
}

export interface AdvisorReport {
  portfolioValue: number;
  diagnostics: Recommendation[];
  ideas: Recommendation[];
  allocation: {
    cash: number;
    invested: number;
    cashLeftover: number;
    items: AllocationItem[];
    before: { hhi: number; topWeight: number };
    after: { hhi: number; topWeight: number };
    note: string;
  };
  timing: string[];
  dataUsed: string[];
  constraints: Constraints;
}

const DECENT = 55;   // composite mínimo para considerar "atractivo relativo"
const STRONG = 65;

function pctStr(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

function hhiFrom(weights: number[]): number {
  const w = weights.filter((x) => x > 0);
  const s = w.reduce((a, b) => a + b, 0);
  if (s <= 0) return 0;
  return w.map((x) => x / s).reduce((a, b) => a + b * b, 0);
}

function sectorWeights(holdings: Holding[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const h of holdings) {
    if (!h.marketValue) continue;
    const s = h.sector || "Otro";
    out[s] = (out[s] ?? 0) + h.weight;
  }
  return out;
}

export function buildAdvice(
  holdings: Holding[],
  scan: ScanInfo[],
  cash: number,
  constraints: Constraints,
  scanAsOf?: string
): AdvisorReport {
  const scanBy = new Map(scan.map((s) => [s.ticker.toUpperCase(), s]));
  const held = new Set(holdings.map((h) => h.ticker.toUpperCase()));
  const V = holdings.reduce((a, h) => a + (h.marketValue ?? 0), 0);
  const secW = sectorWeights(holdings);

  const diagnostics: Recommendation[] = [];

  // --- Diagnóstico: concentración por activo ---
  for (const h of holdings) {
    if (h.weight > constraints.maxWeightAsset) {
      diagnostics.push({
        kind: "reduce", ticker: h.ticker,
        conclusion: `${h.ticker} supera tu límite por activo: evalúa recortar.`,
        justification: [
          `Peso actual ${pctStr(h.weight)} vs. límite ${pctStr(constraints.maxWeightAsset)}.`,
          `Valor de la posición: ${Math.round(h.marketValue ?? 0).toLocaleString("en-US")} USD.`,
        ],
        risks: ["Vender puede generar impuestos y costos; y recortar un ganador reduce el upside si sigue subiendo."],
        conditions: [`Deja de aplicar si subes el límite por activo por encima de ${pctStr(h.weight)}.`],
        composite: scanBy.get(h.ticker.toUpperCase())?.composite,
      });
    }
  }

  // --- Diagnóstico: concentración por sector ---
  for (const [sector, w] of Object.entries(secW)) {
    if (w > constraints.maxWeightSector) {
      diagnostics.push({
        kind: "trim_sector", ticker: sector,
        conclusion: `Sobreexposición al sector ${sector}: evalúa diversificar.`,
        justification: [`Peso del sector ${pctStr(w)} vs. límite ${pctStr(constraints.maxWeightSector)}.`],
        risks: ["Un shock sectorial te afecta desproporcionadamente."],
        conditions: [`Deja de aplicar si reduces el sector por debajo de ${pctStr(constraints.maxWeightSector)}.`],
      });
    }
  }

  // --- Diagnóstico: tenencia con score débil ---
  for (const h of holdings) {
    const s = scanBy.get(h.ticker.toUpperCase());
    if (s && s.composite < 40 && h.marketValue) {
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

  // --- Ideas nuevas: no-tenencias atractivas del scanner ---
  const ideas: Recommendation[] = scan
    .filter((s) => !held.has(s.ticker.toUpperCase()) && s.composite >= STRONG)
    .sort((a, b) => b.composite - a.composite)
    .slice(0, 6)
    .map((s) => ({
      kind: "new_idea" as const, ticker: s.ticker, composite: s.composite,
      conclusion: `${s.ticker}${s.name ? " ("+s.name+")" : ""}: candidata a investigar.`,
      justification: [
        `Score ${Math.round(s.composite)}/100 — value ${Math.round(s.factors.value)}, quality ${Math.round(s.factors.quality)}, growth ${Math.round(s.factors.growth)}, momentum ${Math.round(s.factors.momentum)}.`,
        s.tags.length ? `Etiquetas: ${s.tags.join(", ")}.` : "Sin etiquetas destacadas.",
        s.sector ? `Sector ${s.sector}${(secW[s.sector] ?? 0) > constraints.maxWeightSector ? " — ya sobreexpuesto en tu cartera" : ""}.` : "",
      ].filter(Boolean),
      risks: ["No está en tu cartera: requiere investigación de fundamentales y riesgos antes de comprar."],
      conditions: ["Deja de ser candidata si su score cae por debajo de 65 o rompe tu límite sectorial."],
    }));

  // --- Asignación determinística de capital nuevo ---
  const denom = V + cash;
  const capPerAsset = constraints.maxWeightAsset * denom;  // valor máximo por activo tras invertir

  type Cand = { ticker: string; kind: "add_existing" | "new_idea"; composite: number; current: number; sector: string | null };
  const cands: Cand[] = [];
  // aumentar tenencias fuertes y por debajo del límite
  for (const h of holdings) {
    const s = scanBy.get(h.ticker.toUpperCase());
    if (s && s.composite >= STRONG && h.weight < constraints.maxWeightAsset && (h.marketValue ?? 0) < capPerAsset) {
      cands.push({ ticker: h.ticker, kind: "add_existing", composite: s.composite, current: h.marketValue ?? 0, sector: h.sector });
    }
  }
  // ideas nuevas (top por score)
  for (const s of scan) {
    if (held.has(s.ticker.toUpperCase())) continue;
    if (s.composite >= STRONG) {
      cands.push({ ticker: s.ticker, kind: "new_idea", composite: s.composite, current: 0, sector: s.sector });
    }
  }
  cands.sort((a, b) => b.composite - a.composite);
  const top = cands.slice(0, 5);

  // reparto ponderado por score, respetando el límite por activo
  const items: AllocationItem[] = [];
  let invested = 0;
  const scoreSum = top.reduce((a, c) => a + c.composite, 0) || 1;
  for (const c of top) {
    const target = cash * (c.composite / scoreSum);
    const room = Math.max(0, capPerAsset - c.current);   // cuánto cabe sin romper el límite
    const amount = Math.max(0, Math.min(target, room, cash - invested));
    if (amount < 1) continue;
    invested += amount;
    const newVal = c.current + amount;
    items.push({
      ticker: c.ticker, kind: c.kind, amount: Math.round(amount),
      newWeight: denom > 0 ? newVal / denom : 0, composite: c.composite,
      reason: c.kind === "add_existing"
        ? `Aumentar: ya la tienes, score ${Math.round(c.composite)} y aún por debajo de tu límite por activo.`
        : `Nueva: score ${Math.round(c.composite)}; entra sin romper tu límite por activo.`,
    });
  }
  const cashLeftover = Math.max(0, Math.round(cash - invested));

  const beforeWeights = holdings.map((h) => h.weight);
  const afterVals: Record<string, number> = {};
  for (const h of holdings) afterVals[h.ticker] = h.marketValue ?? 0;
  for (const it of items) afterVals[it.ticker] = (afterVals[it.ticker] ?? 0) + it.amount;
  const afterTotal = Object.values(afterVals).reduce((a, b) => a + b, 0) + cashLeftover;
  const afterWeights = Object.values(afterVals).map((v) => (afterTotal > 0 ? v / afterTotal : 0));

  const timing: string[] = [
    cash > 0 && V > 0 && cash / denom > 0.15
      ? `El monto (${pctStr(cash / denom)} de tu cartera) es grande: escalonar en 2–3 tramos reduce el riesgo de entrada en un solo día.`
      : "Para montos pequeños relativos a tu cartera, un solo tramo suele bastar.",
    "Una candidata etiquetada 'oversold' admite un primer tramo mayor; una en 'momentum' favorece entrada escalonada. Son reglas observables, no pronósticos.",
    "Mantener parte en liquidez es válido si ninguna candidata supera tu umbral de score o romperías tus límites.",
  ];

  return {
    portfolioValue: V,
    diagnostics,
    ideas,
    allocation: {
      cash, invested: Math.round(invested), cashLeftover, items,
      before: { hhi: hhiFrom(beforeWeights), topWeight: Math.max(0, ...beforeWeights) },
      after: { hhi: hhiFrom(afterWeights), topWeight: Math.max(0, ...afterWeights) },
      note: items.length === 0
        ? "Ninguna candidata cumple tus reglas hoy (score o límites): mantener liquidez es la opción consistente."
        : `Sugerencia determinística: repartir ${Math.round(invested).toLocaleString("en-US")} USD por score respetando tu límite por activo; ${cashLeftover.toLocaleString("en-US")} USD quedarían en liquidez.`,
    },
    timing,
    dataUsed: [
      `Posiciones derivadas de tus operaciones (valor de mercado: ${Math.round(V).toLocaleString("en-US")} USD).`,
      scanAsOf ? `Scanner del ${scanAsOf} (score multifactor; atractivo relativo, no predicción).` : "Scanner (último snapshot disponible).",
      `Tus límites: ${pctStr(constraints.maxWeightAsset)} por activo, ${pctStr(constraints.maxWeightSector)} por sector.`,
    ],
    constraints,
  };
}

export { hhiFrom };
