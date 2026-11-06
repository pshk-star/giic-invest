// Valorización de fondos (Fintual) — DETERMINÍSTICA. Participaciones a partir de
// movimientos (compra/venta), valor = participaciones × NAV más reciente × tipo de cambio.
// Multimoneda: el valor se expresa en la moneda del fondo y en la moneda base.

export interface FundMove {
  side: "buy" | "sell";
  quantity: number | null;  // participaciones
  price: number | null;     // NAV de la operación (moneda del fondo)
  fees: number;
}

export interface FundValuation {
  units: number;             // participaciones netas
  netContributedFundCcy: number; // capital neto aportado (compras − ventas), moneda del fondo
  latestNav: number | null;
  navDate: string | null;
  valueFundCcy: number | null;   // participaciones × NAV
  valueBase: number | null;      // convertido a moneda base
  gainFundCcy: number | null;    // valor − aportado
  currency: string;
  stale: boolean;            // true si no hay NAV utilizable
}

// fxToBase = valor de 1 unidad de la moneda del fondo en la moneda base
// (p. ej. MXN->USD = 0.0538). Si currency === base, pasar 1.
export function valueFund(
  moves: FundMove[], latestNav: number | null, navDate: string | null,
  currency: string, fxToBase: number | null,
): FundValuation {
  let units = 0, net = 0;
  for (const m of moves) {
    const q = m.quantity ?? 0, p = m.price ?? 0, fee = m.fees ?? 0;
    if (m.side === "buy") { units += q; net += q * p + fee; }
    else if (m.side === "sell") { units -= q; net -= q * p - fee; }
  }
  units = Math.max(0, Number(units.toFixed(8)));
  const valueFundCcy = latestNav != null && units > 0 ? units * latestNav : (units === 0 ? 0 : null);
  const valueBase = valueFundCcy != null && fxToBase != null ? valueFundCcy * fxToBase : null;
  const gainFundCcy = valueFundCcy != null ? valueFundCcy - net : null;
  return {
    units, netContributedFundCcy: net, latestNav, navDate,
    valueFundCcy, valueBase, gainFundCcy, currency,
    stale: latestNav == null && units > 0,
  };
}

// Convierte un monto entre monedas usando el mapa fx (base USD): fx[ccy] = valor de 1 ccy en USD.
export function toBase(amount: number, currency: string, base: string, fxUsd: Record<string, number>): number | null {
  if (currency === base) return amount;
  const cUsd = currency === "USD" ? 1 : fxUsd[currency];
  const bUsd = base === "USD" ? 1 : fxUsd[base];
  if (cUsd == null || bUsd == null) return null;
  return amount * (cUsd / bUsd); // (ccy->USD) then (USD->base)
}
