export const pct = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined || !isFinite(x) ? "—" : `${(x * 100).toFixed(digits)}%`;

export const money = (x: number | null | undefined, ccy = "USD") =>
  x === null || x === undefined || !isFinite(x)
    ? "—"
    : new Intl.NumberFormat("es-MX", { style: "currency", currency: ccy, maximumFractionDigits: 0 }).format(x);

export const num = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined || !isFinite(x) ? "—" : x.toFixed(digits);

// Formato compacto y SIN AMBIGÜEDAD de unidades para cifras grandes (p. ej. market
// cap). Usa palabras en español: "millones" (1e6), "mil millones" (1e9), "billones"
// (1e12) — evita la confusión billion(EN)=mil millones vs billón(ES)=1e12.
export const moneyScale = (x: number | null | undefined, ccy = "USD") => {
  if (x === null || x === undefined || !isFinite(x)) return "—";
  const a = Math.abs(x), sign = x < 0 ? "-" : "";
  if (a >= 1e12) return `${sign}$${(a / 1e12).toFixed(2)} billones ${ccy}`;
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(a / 1e9 >= 100 ? 0 : 1)} mil millones ${ccy}`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(0)} millones ${ccy}`;
  return money(x, ccy);
};
