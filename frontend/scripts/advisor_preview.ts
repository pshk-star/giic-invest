// Etapa A — Vista previa del Investment Advisor unificado con DATOS REALES (solo lectura). Reutiliza el
// orquestador advisor-engine (sin duplicar lógica de decisión) y arma el ScanInput desde Supabase REST.
// Imprime la recomendación para verificar el resultado funcional end-to-end. No escribe nada.
import { derivePositions, type Txn, type InstrumentMeta, type Split } from "../src/core/portfolio-tx";
import { type ScanInput, type ScanCandidate, type InstrumentKind } from "../src/core/opportunity-scanner";
import { buildUnifiedAdvisor } from "../src/core/advisor-engine";
import { profileFromSettings, missingEssentials, investableAmount, type Profile } from "../src/core/advisor-profile";
import type { Adv3Valuation } from "../src/core/advisor3";
import type { CompanyValuation } from "../src/core/fundval";

const BASE = (process.env.SUPABASE_URL || "").replace(/\/$/, "") + "/rest/v1";
const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || "";
const ETF = ["etf", "fund", "etn", "mutualfund"];
if (!BASE.startsWith("http") || !KEY) { console.error("faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY"); process.exit(1); }
const H: Record<string, string> = { apikey: KEY, Authorization: `Bearer ${KEY}` };
async function get(p: string, params: Record<string, string>): Promise<any[]> {
  const r = await fetch(`${BASE}/${p}?${new URLSearchParams(params)}`, { headers: H });
  if (!r.ok) throw new Error(`GET ${p} ${r.status} ${await r.text()}`);
  return r.json();
}
function kindOf(ac: string | null, s: string | null): InstrumentKind {
  const a = (ac || "").toLowerCase();
  if (ETF.includes(a)) return "etf";
  if (s && /financ|bank|banco|insurance|seguro/i.test(s)) return "banco";
  if (a && !["equity", "stock", "adr", "common"].includes(a)) return "otro";
  return "empresa";
}
function mm(cv: CompanyValuation | undefined, m: string): { m: number | null; c: string | null } {
  const b = cv?.modelos.find((x) => x.modelo === m);
  if (!b || b.disponible === false || b.margen_seguridad_pct == null) return { m: null, c: null };
  return { m: b.margen_seguridad_pct / 100, c: b.confianza ?? null };
}

async function main() {
  const settingsRows = await get("settings", { select: "*", limit: "1" });
  let profile: Profile = profileFromSettings(settingsRows[0] ?? null);
  const miss = missingEssentials(profile);
  let demo = false;
  if (miss.length) {   // perfil incompleto: para la VISTA PREVIA usamos un perfil DEMO etiquetado (no inventa persistente)
    demo = true;
    profile = { ...profile, baseCurrency: profile.baseCurrency ?? "USD", capitalAvailable: profile.capitalAvailable ?? 3000, riskTolerance: profile.riskTolerance ?? "moderado", monthlyContribution: profile.monthlyContribution ?? 3000, minCash: profile.minCash ?? 0, horizonYears: profile.horizonYears ?? 10, maxWeightPerAsset: null, maxWeightPerSector: null };
  }

  const txns = (await get("transactions", { select: "*" })) as Txn[];
  const ptk = [...new Set(txns.map((t) => t.ticker.toUpperCase()))];
  const scan = await get("v_latest_scan", { select: "ticker,sector,composite,rank", order: "rank" });
  const fvRows = await get("pit_snapshots", { select: "ticker,payload", kind: "eq.fundamental_valuation", order: "snapshot_date.desc,captured_at.desc" });
  const fv: Record<string, CompanyValuation> = {};
  for (const r of fvRows) { const t = String(r.ticker).toUpperCase(); if (!fv[t]) fv[t] = r.payload; }
  const universe = [...new Set([...ptk, ...scan.map((s: any) => String(s.ticker).toUpperCase()), ...Object.keys(fv)])];
  const inF = "in.(" + universe.join(",") + ")";
  const instr: Record<string, InstrumentMeta> = {};
  for (const r of await get("instruments", { select: "ticker,name,asset_class,status,currency,sector,exchange", ticker: inF, order: "ticker" })) instr[String(r.ticker).toUpperCase()] = r as any;
  const prices: Record<string, any> = {};
  for (const r of await get("prices", { select: "ticker,close,currency,as_of", ticker: inF, order: "ticker" })) prices[String(r.ticker).toUpperCase()] = r;
  const ca = (await get("corporate_actions", { select: "ticker,ratio,ex_date", ticker: "in.(" + ptk.join(",") + ")" })) as Split[];
  const positionsAll = derivePositions(txns, prices as any, instr as any, ca).filter((p) => (p.marketValue ?? 0) > 0);
  const total = positionsAll.reduce((s, p) => s + (p.marketValue ?? 0), 0);

  const histTk = [...new Set([...positionsAll.map((p) => p.ticker), ...universe])];
  const priceHistory: Record<string, { as_of: string; close: number }[]> = {};
  for (const t of histTk) priceHistory[t] = (await get("price_history", { select: "as_of,close", ticker: `eq.${t}`, order: "as_of" })).map((b: any) => ({ as_of: b.as_of, close: Number(b.close) }));

  const valuation: Record<string, Adv3Valuation> = {};
  const candidates: ScanCandidate[] = [];
  const sectorOf = (t: string) => instr[t]?.sector ?? (scan.find((s: any) => String(s.ticker).toUpperCase() === t)?.sector ?? null);
  for (const t of universe) {
    const prod = mm(fv[t], "DCF_productivo"); const giic = mm(fv[t], "FCFF_GIIC");
    valuation[t] = { productiveMargin: prod.m, productiveConfidence: prod.m != null ? "media" : null, fcffMargin: giic.m, fcffConfidence: (giic.c as any) ?? null, priceComparable: true };
    const s = sectorOf(t); const ac = instr[t]?.asset_class ?? null;
    candidates.push({ ticker: t, name: instr[t]?.name ?? null, sector: s, country: null, currency: instr[t]?.currency ?? null, assetClass: ac, kind: kindOf(ac, s), inPortfolio: ptk.includes(t), composite: scan.find((x: any) => String(x.ticker).toUpperCase() === t)?.composite ?? null });
  }
  const scanInput: ScanInput = {
    candidates, valuation, fundamentals: {},
    portfolio: { positions: positionsAll.map((p) => ({ ticker: p.ticker, name: p.name, sector: instr[p.ticker]?.sector ?? null, country: null, currency: p.currency, assetClass: p.asset_class, marketValue: p.marketValue ?? 0, weight: total > 0 ? (p.marketValue ?? 0) / total : 0 })), cash: profile.capitalAvailable ?? 0 },
    priceHistory, contributions: [1000], constraints: { maxPositionWeight: 0.45, maxSectorWeight: 0.50, minMarginToBuy: 0.10 },
    fcffFallback: process.env.FF_VALPOLICY === "1",
  };

  const r = buildUnifiedAdvisor({ profile, scanInput });
  console.log(JSON.stringify({
    perfil_demo: demo, moneda: r.currency, aporte: investableAmount(profile), postura: r.posture,
    resumen: r.executiveSummary,
    acciones: r.positions.map((p) => ({ t: p.ticker, accion: p.action, margen: p.margin, fuente: p.source, peso: p.weight })),
    dinero_nuevo: { elegido: r.newMoney.chosen, legs: r.newMoney.legs.map((l) => ({ t: l.ticker, monto: l.amount })), efectivo: r.newMoney.cashKept },
    oportunidades_top: r.opportunities.slice(0, 10).map((o) => ({ t: o.ticker, clase: o.class, comprable: o.buyable, margen: o.margin })),
    pendientes_analisis: r.researchPriorities.map((x) => x.ticker),
    riesgos: r.risks, topes: r.constraintsUsed,
  }, null, 2));
}
main().catch((e) => { console.error(e); process.exit(1); });
