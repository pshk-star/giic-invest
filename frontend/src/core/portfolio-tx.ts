// Núcleo de cartera por TRANSACCIONES (Fase A). El registro de operaciones es la
// fuente de verdad; las posiciones se DERIVAN de aquí. Corre en el navegador.
//
// Metodología de costo: PROMEDIO PONDERADO sobre el precio (sin comisiones) para el
// "precio promedio" que se muestra; las comisiones se contabilizan aparte y afectan
// el P&L realizado. En una venta, el P&L realizado = (precio venta − costo promedio)
// × cantidad − comisiones; el costo promedio de lo que queda no cambia (método del
// promedio). Consistente y sin doble conteo.

export type Side = "buy" | "sell" | "dividend" | "deposit" | "withdrawal" | "split";

export interface Txn {
  id: string;
  ticker: string;
  side: Side;
  quantity: number | null;
  price: number | null;
  fees: number;
  amount: number | null;
  currency: string;
  executed_at: string; // YYYY-MM-DD
  notes?: string | null;
  created_at?: string;
  fund_id?: string | null; // NOT NULL => movimiento de fondo (Fintual); NULL => acción/ETF
}

export interface PriceInfo {
  close: number;
  as_of: string;
  currency: string;
}

// Evento corporativo (split). ratio = multiplicador de acciones (10-for-1 => 10;
// reverse 1-for-10 => 0.1). ex_date = primer día en base ajustada (YYYY-MM-DD).
export interface Split {
  ticker: string;
  ratio: number;
  ex_date: string;
}

// Factor acumulado a aplicar a una operación: producto de los ratios de los splits
// cuyo ex_date es POSTERIOR a la fecha de la operación (una compra previa al split se
// ajusta; una compra en o después del ex_date no). Idempotente: se recalcula siempre
// desde las transacciones inmutables, nunca se aplica dos veces.
export function splitFactor(splits: Split[], ticker: string, dateStr: string): number {
  const tk = ticker.toUpperCase();
  let f = 1;
  for (const s of splits) if (s.ticker.toUpperCase() === tk && s.ex_date > dateStr) f *= s.ratio;
  return f;
}

export interface InstrumentMeta {
  name: string | null;
  asset_class: string | null;
  status: string | null;
  currency?: string | null;
  sector?: string | null;
  exchange?: string | null;
}

export interface DerivedPosition {
  ticker: string;
  name: string | null;
  asset_class: string | null;
  status: string | null;
  currency: string;
  qty: number;
  avgCost: number;        // costo promedio por acción, SIN comisiones
  investedExFees: number; // costo de lo que queda (avgCost * qty)
  feesPaid: number;
  realized: number;       // P&L realizado acumulado (incluye comisiones de venta)
  dividends: number;
  price: number | null;
  priceAsOf: string | null;
  marketValue: number | null;
  unrealized: number | null;
  unrealizedPct: number | null;
}

function chrono(a: Txn, b: Txn): number {
  if (a.executed_at !== b.executed_at) return a.executed_at < b.executed_at ? -1 : 1;
  return (a.created_at ?? "") < (b.created_at ?? "") ? -1 : 1;
}

export function derivePositions(
  txns: Txn[],
  prices: Record<string, PriceInfo> = {},
  instruments: Record<string, InstrumentMeta> = {},
  splits: Split[] = []
): DerivedPosition[] {
  const byTicker = new Map<string, Txn[]>();
  for (const t of txns) {
    const k = t.ticker.toUpperCase();
    if (!byTicker.has(k)) byTicker.set(k, []);
    byTicker.get(k)!.push(t);
  }

  const out: DerivedPosition[] = [];
  for (const [ticker, list] of byTicker) {
    list.sort(chrono);
    let qty = 0, invested = 0, fees = 0, realized = 0, dividends = 0;
    let currency = "USD";
    for (const t of list) {
      currency = t.currency || currency;
      // Ajuste automático por split: la compra/venta previa al ex_date se expresa en
      // acciones POST-split (cantidad ×factor, precio ÷factor). El costo total (q×p) no
      // cambia. Los dividendos (efectivo) NO se escalan.
      const fac = splitFactor(splits, ticker, t.executed_at);
      const q = (t.quantity ?? 0) * fac;
      const p = fac !== 0 ? (t.price ?? 0) / fac : (t.price ?? 0);
      const f = t.fees ?? 0;
      if (t.side === "buy") {
        qty += q;
        invested += q * p;
        fees += f;
      } else if (t.side === "sell") {
        const avg = qty > 0 ? invested / qty : 0;
        const sellQty = Math.min(q, qty);
        realized += (p - avg) * sellQty - f;
        invested -= avg * sellQty;
        qty -= sellQty;
        fees += f;
      } else if (t.side === "dividend") {
        dividends += t.amount ?? (t.quantity ?? 0) * (t.price ?? 0);  // efectivo, sin escalar
      } else if (t.side === "split" && (t.quantity ?? 0) > 0) {
        qty *= (t.quantity ?? 1);   // split MANUAL (ratio); el automático va por `splits`
      }
      // deposit/withdrawal: efectivo de cuenta, no afecta posiciones individuales
    }
    if (qty <= 1e-9 && Math.abs(realized) < 1e-9 && dividends < 1e-9) continue;

    const avgCost = qty > 0 ? invested / qty : 0;
    const meta = instruments[ticker] ?? { name: null, asset_class: null, status: null };
    const pinfo = prices[ticker];
    const price = pinfo ? pinfo.close : null;
    const marketValue = price !== null ? price * qty : null;
    const costRemaining = avgCost * qty;
    const unrealized = marketValue !== null ? marketValue - costRemaining : null;
    const unrealizedPct = unrealized !== null && costRemaining > 0 ? unrealized / costRemaining : null;

    out.push({
      ticker,
      name: meta.name,
      asset_class: meta.asset_class,
      status: meta.status,
      currency,
      qty: round(qty, 6),
      avgCost,
      investedExFees: costRemaining,
      feesPaid: fees,
      realized,
      dividends,
      price,
      priceAsOf: pinfo ? pinfo.as_of : null,
      marketValue,
      unrealized,
      unrealizedPct,
    });
  }
  out.sort((a, b) => (b.marketValue ?? 0) - (a.marketValue ?? 0));
  return out;
}

export interface PortfolioTotals {
  marketValue: number;
  costBasis: number;
  unrealized: number;
  unrealizedPct: number | null;
  realized: number;
  dividends: number;
  missingPrices: string[];
  weights: Record<string, number>;
}

export function portfolioTotals(positions: DerivedPosition[]): PortfolioTotals {
  let mv = 0, cost = 0, realized = 0, dividends = 0;
  const missing: string[] = [];
  for (const p of positions) {
    realized += p.realized;
    dividends += p.dividends;
    if (p.qty <= 1e-9) continue;
    cost += p.investedExFees;
    if (p.marketValue !== null) mv += p.marketValue;
    else missing.push(p.ticker);
  }
  const weights: Record<string, number> = {};
  for (const p of positions) {
    if (p.marketValue && mv > 0) weights[p.ticker] = p.marketValue / mv;
  }
  const unrealized = mv - cost;
  return {
    marketValue: mv,
    costBasis: cost,
    unrealized,
    unrealizedPct: cost > 0 ? unrealized / cost : null,
    realized,
    dividends,
    missingPrices: missing,
    weights,
  };
}

function round(x: number, d: number): number {
  const f = Math.pow(10, d);
  return Math.round(x * f) / f;
}
