export const pct = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined || !isFinite(x) ? "—" : `${(x * 100).toFixed(digits)}%`;

export const money = (x: number | null | undefined, ccy = "USD") =>
  x === null || x === undefined || !isFinite(x)
    ? "—"
    : new Intl.NumberFormat("es-MX", { style: "currency", currency: ccy, maximumFractionDigits: 0 }).format(x);

export const num = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined || !isFinite(x) ? "—" : x.toFixed(digits);
