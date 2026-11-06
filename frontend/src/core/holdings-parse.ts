// Parser/normalizador de archivos de holdings OFICIALES (CSV/XLSX ya convertido a matriz).
// DETERMINÍSTICO. Detecta columnas por sinónimos y normaliza pesos a FRACCIÓN (0.07=7%).
// No inventa: si no hay columna de peso o nombre/ticker, devuelve líneas sin peso y status parcial.

export interface ParsedLine {
  ticker: string | null; name: string | null; cusip: string | null;
  sector: string | null; assetClass: string; weight: number | null;
  lineKey: string; companyKey: string | null;
}
export interface ParsedHoldings {
  lines: ParsedLine[]; weightSum: number; nLines: number;
  status: "complete" | "partial"; columns: Record<string, string | null>;
}

const NAME = ["name", "security name", "holding name", "long name", "description", "issuer name", "holding"];
const TICK = ["ticker", "holding ticker", "symbol", "ticker symbol"];
const WT = ["weight", "weight (%)", "% weight", "percentage of fund", "% of net assets",
  "% of fund", "weighting", "weightings", "weight %", "fund weight", "% weight (%)", "marketvaluepercentage"];
const CUS = ["cusip", "security identifier", "identifier"];
const SEC = ["sector", "gics sector", "industry", "gics sector name"];
const CLS = ["asset class", "security type", "class of holdings", "type", "asset_class"];

export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let field = "", row: string[] = [], inQ = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQ) {
      if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else inQ = false; }
      else field += c;
    } else if (c === '"') inQ = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field); field = ""; rows.push(row); row = []; }
    else if (c !== "\r") field += c;
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  return rows.filter((r) => r.some((x) => x.trim() !== ""));
}

function num(x: string | undefined): number | null {
  if (x == null) return null;
  const v = parseFloat(String(x).replace(/[, %]/g, "").trim());
  return isFinite(v) ? v : null;
}
function pick(header: string[], syns: string[]): number {
  const low = header.map((h) => h.trim().toLowerCase());
  for (const s of syns) { const i = low.indexOf(s); if (i >= 0) return i; }
  for (let i = 0; i < low.length; i++) if (syns.some((s) => low[i].includes(s))) return i;
  return -1;
}
function headerRow(m: string[][]): number {
  for (let i = 0; i < Math.min(40, m.length); i++) {
    const low = m[i].map((c) => c.trim().toLowerCase());
    const hasW = low.some((c) => WT.includes(c) || c.includes("weight") || c.includes("% of"));
    const hasNT = low.some((c) => NAME.includes(c) || TICK.includes(c) || c === "name" || c === "ticker");
    if (hasW && hasNT) return i;
  }
  return -1;
}

export function normalizeHoldings(matrix: string[][]): ParsedHoldings {
  const hr = headerRow(matrix);
  if (hr < 0) return { lines: [], weightSum: 0, nLines: 0, status: "partial", columns: {} };
  const header = matrix[hr];
  const iN = pick(header, NAME), iT = pick(header, TICK), iW = pick(header, WT),
    iC = pick(header, CUS), iS = pick(header, SEC), iCl = pick(header, CLS);
  const raw: { name: string | null; ticker: string | null; cusip: string | null; sector: string | null; cls: string; w: number | null }[] = [];
  for (let r = hr + 1; r < matrix.length; r++) {
    const row = matrix[r];
    const name = iN >= 0 ? (row[iN] || "").trim() : "";
    const ticker = iT >= 0 ? (row[iT] || "").trim() : "";
    if (!name && !ticker) continue;
    const w = iW >= 0 ? num(row[iW]) : null;
    const clsRaw = (iCl >= 0 ? (row[iCl] || "") : "").toLowerCase();
    let cls = "equity";
    const blob = (name + " " + clsRaw).toLowerCase();
    if (blob.includes("cash") || blob.includes("money market") || blob.includes("u.s. dollar")) cls = "cash";
    else if (/(future|swap|option|forward|derivative)/.test(clsRaw)) cls = "derivative";
    else if (/(bond|treasury|note|bill)/.test(clsRaw)) cls = "bond";
    raw.push({ name: name || null, ticker: ticker || null, cusip: iC >= 0 ? (row[iC] || "").trim() || null : null,
      sector: iS >= 0 ? (row[iS] || "").trim() || null : null, cls, w });
  }
  // normaliza pesos a fracción: si la suma/máximo parece porcentaje (>1.5), divide por 100
  const ws = raw.map((r) => r.w).filter((x): x is number => x != null);
  const maxw = ws.length ? Math.max(...ws.map(Math.abs)) : 0;
  const asPct = maxw > 1.5;
  const lines: ParsedLine[] = raw.map((r, idx) => {
    const w = r.w == null ? null : (asPct ? r.w / 100 : r.w);
    const companyKey = r.cusip && r.cusip.length >= 6 ? r.cusip.slice(0, 6) : (r.ticker || null);
    const lineKey = r.cusip || r.ticker || `UNIDENT-${idx}`;
    return { ticker: r.ticker, name: r.name, cusip: r.cusip, sector: r.sector,
      assetClass: r.cls, weight: w, lineKey, companyKey };
  });
  const weightSum = lines.reduce((s, l) => s + (l.weight ?? 0), 0);
  const status: "complete" | "partial" = (weightSum >= 0.97 && weightSum <= 1.03 && lines.length >= 1) ? "complete" : "partial";
  return { lines, weightSum, nLines: lines.length, status,
    columns: { name: header[iN] ?? null, ticker: header[iT] ?? null, weight: header[iW] ?? null } };
}
