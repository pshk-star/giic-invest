// Cobertura de cartera en TRES niveles, SIEMPRE ponderada por valor de mercado
// (no por número de tickers). Evita presentar una proyección parcial como si
// representara toda la cartera. No elimina posiciones silenciosamente.
//
//  A. Precio   — ¿hay un precio válido para valorar la posición?
//  B. Estadística — ¿hay historial suficiente para simular su riesgo?
//  C. Fundamental — ¿hay datos para construir escenarios de valoración económica?

export interface CovItem {
  ticker: string;
  marketValue: number;
  hasPrice: boolean;
  statOk: boolean;        // historial suficiente para el motor estadístico
  fundOk: boolean;        // valoración fundamental disponible
  asOf?: string | null;   // fecha del dato de precio/valuación (para "más antiguo")
}

export interface CoverageReport {
  total: number;
  priceValue: number; statValue: number; fundValue: number; uncoveredValue: number;
  pricePct: number; statPct: number; fundPct: number; uncoveredPct: number;
  // instrumentos que más pesan en el hueco (sin estadística), por valor de mercado
  topStatGap: { ticker: string; marketValue: number; weight: number }[];
  topFundGap: { ticker: string; marketValue: number; weight: number }[];
  oldestAsOf: string | null;
  statThreshold: number; fundThreshold: number;
  statSufficient: boolean;   // ¿publicar banda consolidada como representativa?
  fundSufficient: boolean;
}

export interface CoverageOpts { statThreshold?: number; fundThreshold?: number; }

// Umbrales por defecto, justificados y CONFIGURABLES (no elegidos para favorecer un
// resultado): 80% del patrimonio con simulación estadística para considerar la banda
// representativa de TODA la cartera; 60% con valoración fundamental para un consolidado
// fundamental. Por debajo, el resultado se marca PARCIAL.
const DEFAULTS = { statThreshold: 0.80, fundThreshold: 0.60 };

export function computeCoverage(items: CovItem[], opts?: CoverageOpts): CoverageReport {
  const statThreshold = opts?.statThreshold ?? DEFAULTS.statThreshold;
  const fundThreshold = opts?.fundThreshold ?? DEFAULTS.fundThreshold;
  const total = items.reduce((s, it) => s + Math.max(0, it.marketValue), 0);
  const sumIf = (pred: (it: CovItem) => boolean) =>
    items.reduce((s, it) => s + (pred(it) ? Math.max(0, it.marketValue) : 0), 0);

  const priceValue = sumIf((it) => it.hasPrice);
  const statValue = sumIf((it) => it.hasPrice && it.statOk);
  const fundValue = sumIf((it) => it.hasPrice && it.fundOk);
  const uncoveredValue = Math.max(0, total - statValue);  // sin simulación estadística

  const pct = (v: number) => (total > 0 ? v / total : 0);
  const gap = (pred: (it: CovItem) => boolean) =>
    items.filter((it) => !pred(it) && it.marketValue > 0)
      .sort((a, b) => b.marketValue - a.marketValue)
      .slice(0, 5)
      .map((it) => ({ ticker: it.ticker, marketValue: it.marketValue, weight: pct(it.marketValue) }));

  const dates = items.map((it) => it.asOf).filter((d): d is string => !!d).sort();
  const oldestAsOf = dates.length ? dates[0] : null;

  const statPct = pct(statValue);
  const fundPct = pct(fundValue);
  return {
    total,
    priceValue, statValue, fundValue, uncoveredValue,
    pricePct: pct(priceValue), statPct, fundPct, uncoveredPct: pct(uncoveredValue),
    topStatGap: gap((it) => it.hasPrice && it.statOk),
    topFundGap: gap((it) => it.hasPrice && it.fundOk),
    oldestAsOf, statThreshold, fundThreshold,
    statSufficient: statPct >= statThreshold,
    fundSufficient: fundPct >= fundThreshold,
  };
}
