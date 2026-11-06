// Portfolio X-Ray — exposición económica EFECTIVA por empresa. DETERMINÍSTICO.
// Exposición(empresa) = posición directa + Σ(valor en cada ETF × peso de la empresa en el ETF).
// No inventa: lo que el ETF no identifica (pesos que no suman 100%, efectivo, derivados) se
// reporta como "desconocido", nunca se atribuye a acciones. Sin doble conteo: el valor de un
// ETF se DISTRIBUYE entre sus subyacentes; el ETF no se cuenta además como línea propia.

export interface PortfolioHolding {
  ticker: string;      // símbolo de la posición (acción o ETF)
  isEtf: boolean;
  valueUsd: number;    // valor de mercado de la posición en USD
}

export interface EtfWeight {
  etf: string;
  ticker: string;      // subyacente
  weight: number;      // fracción (0.07 = 7%)
  name?: string;
  assetClass?: string; // 'equity' | 'cash' | 'derivative' | 'bond' | 'other'
  sector?: string;
}

export interface ExposureSource { via: string; amount: number; } // 'directo' o símbolo del ETF
export interface CompanyExposure {
  ticker: string;
  name?: string;
  sector?: string;
  direct: number;
  indirect: number;
  total: number;
  sources: ExposureSource[];
}

export interface XRayResult {
  byCompany: CompanyExposure[];   // ordenado por exposición total desc
  totalUsd: number;               // valor total de la cartera considerada
  identifiedUsd: number;          // exposición atribuida a empresas concretas
  unknownUsd: number;             // efectivo/derivados/pesos no identificados dentro de ETFs
  identifiedPct: number;          // identifiedUsd / totalUsd
  etfsWithoutHoldings: string[];  // ETFs en cartera sin datos de holdings (cobertura incompleta)
}

export function effectiveExposure(
  holdings: PortfolioHolding[],
  etfWeights: EtfWeight[],
): XRayResult {
  const byEtf = new Map<string, EtfWeight[]>();
  for (const w of etfWeights) {
    const k = w.etf.toUpperCase();
    (byEtf.get(k) ?? byEtf.set(k, []).get(k)!).push(w);
  }

  const comp = new Map<string, CompanyExposure>();
  const bump = (ticker: string, name: string | undefined, amount: number, via: string, kind: "direct" | "indirect", sector?: string) => {
    const k = ticker.toUpperCase();
    const c = comp.get(k) ?? { ticker: k, name, direct: 0, indirect: 0, total: 0, sources: [] };
    if (!c.name && name) c.name = name;
    if (!c.sector && sector) c.sector = sector;
    if (kind === "direct") c.direct += amount; else c.indirect += amount;
    c.total += amount;
    const src = c.sources.find((s) => s.via === via);
    if (src) src.amount += amount; else c.sources.push({ via, amount });
    comp.set(k, c);
  };

  let totalUsd = 0, unknownUsd = 0;
  const etfsWithoutHoldings: string[] = [];

  for (const h of holdings) {
    if (h.valueUsd <= 0) continue;
    totalUsd += h.valueUsd;
    if (!h.isEtf) {
      bump(h.ticker, undefined, h.valueUsd, "directo", "direct");
      continue;
    }
    const ws = byEtf.get(h.ticker.toUpperCase());
    if (!ws || ws.length === 0) {
      etfsWithoutHoldings.push(h.ticker.toUpperCase());
      unknownUsd += h.valueUsd; // sin holdings: todo su valor es exposición desconocida
      continue;
    }
    let distributed = 0;
    for (const w of ws) {
      const amt = h.valueUsd * w.weight;
      if ((w.assetClass ?? "equity") !== "equity") { unknownUsd += amt; distributed += amt; continue; }
      bump(w.ticker, w.name, amt, h.ticker.toUpperCase(), "indirect", w.sector);
      distributed += amt;
    }
    // peso no identificado (no suma 100%): efectivo/otros -> desconocido
    const residual = h.valueUsd - distributed;
    if (residual > 1e-9) unknownUsd += residual;
  }

  const byCompany = [...comp.values()].sort((a, b) => b.total - a.total);
  const identifiedUsd = byCompany.reduce((s, c) => s + c.total, 0);
  return {
    byCompany, totalUsd, identifiedUsd, unknownUsd,
    identifiedPct: totalUsd > 0 ? identifiedUsd / totalUsd : 0,
    etfsWithoutHoldings: [...new Set(etfsWithoutHoldings)],
  };
}
