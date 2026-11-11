// P2.6 — Emisión FORMAL de una decisión (rol de servicio, en CI). Reutiliza el MOTOR TS (sin duplicar
// lógica): arma el ScanInput como la página, corre Scanner + planner (heurística) + registro, y escribe
// un snapshot INMUTABLE a pit_snapshots (kind='decision_record'). Idempotente por decisionId. Esto es
// "registrar cuando se emite formalmente", no por cada render. NO ejecuta operaciones.
//
// Uso (CI): SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY [+ APORTE, FF_VALPOLICY]. npx tsx scripts/emit_decision.ts
import { derivePositions, type Txn, type InstrumentMeta, type Split } from "../src/core/portfolio-tx";
import { buildScanner, type ScanInput, type ScanCandidate, type InstrumentKind } from "../src/core/opportunity-scanner";
import { buildAllocationPlan } from "../src/core/allocation-planner";
import { buildDecisionRecord } from "../src/core/decision-record";
import type { Adv3Valuation } from "../src/core/advisor3";
import type { CompanyValuation } from "../src/core/fundval";

const BASE = (process.env.SUPABASE_URL || "").replace(/\/$/, "") + "/rest/v1";
const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || "";
const ETF = ["etf", "fund", "etn", "mutualfund"];
const BENCH = process.env.BENCHMARK || "SPY";
const CONTRIB = Math.max(0, Number(process.env.APORTE || "3000") || 3000);
const FF_VALPOLICY = process.env.FF_VALPOLICY === "1";

if (!BASE.startsWith("http") || !KEY) { console.error("faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY"); process.exit(1); }
const H: Record<string, string> = { apikey: KEY, Authorization: `Bearer ${KEY}` };

async function get(path: string, params: Record<string, string>): Promise<any[]> {
  const qs = new URLSearchParams(params).toString();
  const r = await fetch(`${BASE}/${path}?${qs}`, { headers: H });
  if (!r.ok) throw new Error(`GET ${path} ${r.status} ${await r.text()}`);
  return r.json();
}
async function post(path: string, rows: any[], onConflict: string): Promise<void> {
  const r = await fetch(`${BASE}/${path}?on_conflict=${onConflict}`, {
    method: "POST", headers: { ...H, "Content-Type": "application/json", Prefer: "resolution=ignore-duplicates,return=minimal" },
    body: JSON.stringify(rows),
  });
  if (!r.ok) throw new Error(`POST ${path} ${r.status} ${await r.text()}`);
}

function kindOf(ac: string | null, sector: string | null): InstrumentKind {
  const a = (ac || "").toLowerCase();
  if (ETF.includes(a)) return "etf";
  if (sector && /financ|bank|banco|insurance|seguro/i.test(sector)) return "banco";
  if (a && !["equity", "stock", "adr", "common"].includes(a)) return "otro";
  return "empresa";
}
function modelMargin(cv: CompanyValuation | undefined, modelo: string): { m: number | null; c: string | null } {
  const b = cv?.modelos.find((x) => x.modelo === modelo);
  if (!b || b.disponible === false || b.margen_seguridad_pct == null) return { m: null, c: null };
  return { m: b.margen_seguridad_pct / 100, c: b.confianza ?? null };
}

async function main() {
  const txns = (await get("transactions", { select: "*" })) as Txn[];
  const ptk = [...new Set(txns.map((t) => t.ticker.toUpperCase()))];
  const scan = await get("v_latest_scan", { select: "ticker,sector,composite,rank", order: "rank" });
  const fvRows = await get("pit_snapshots", { select: "ticker,payload,snapshot_date,captured_at", kind: "eq.fundamental_valuation", order: "snapshot_date.desc,captured_at.desc" });
  const fv: Record<string, CompanyValuation> = {};
  for (const r of fvRows) { const t = String(r.ticker).toUpperCase(); if (!fv[t]) fv[t] = r.payload; }   // vigente = más reciente
  const universe = [...new Set([...ptk, ...scan.map((s: any) => String(s.ticker).toUpperCase()), ...Object.keys(fv)])];

  const inFilter = "in.(" + universe.join(",") + ")";
  const instrRows = await get("instruments", { select: "ticker,name,asset_class,status,currency,sector,exchange,adr_ratio", ticker: inFilter, order: "ticker" });
  const instruments: Record<string, InstrumentMeta & { adr_ratio?: number }> = {};
  for (const r of instrRows) instruments[String(r.ticker).toUpperCase()] = r;
  const priceRows = await get("prices", { select: "ticker,close,currency,as_of", ticker: inFilter, order: "ticker" });
  const prices: Record<string, { close: number; as_of: string; currency: string }> = {};
  for (const r of priceRows) prices[String(r.ticker).toUpperCase()] = { close: r.close, as_of: r.as_of, currency: r.currency };
  const caRows = (await get("corporate_actions", { select: "ticker,ratio,ex_date", ticker: "in.(" + ptk.join(",") + ")" })) as Split[];
  const fundRows = await get("fundamentals", { select: "ticker,payload", ticker: inFilter, order: "ticker" });
  const fundamentals: Record<string, { roic?: number | null; revGrowth?: number | null; netMargin?: number | null; operatingMargin?: number | null; fcfTtm?: number | null }> = {};
  for (const r of fundRows) {
    const p = (r.payload || {}) as any;
    fundamentals[String(r.ticker).toUpperCase()] = { roic: p.roic ?? null, revGrowth: p.rev_growth_yoy ?? null, netMargin: p.net_margin ?? null, operatingMargin: p.operating_margin ?? null, fcfTtm: p.fcf_ttm ?? null };
  }

  const positionsAll = derivePositions(txns, prices as any, instruments as any, caRows).filter((p) => (p.marketValue ?? 0) > 0);
  const total = positionsAll.reduce((s, p) => s + (p.marketValue ?? 0), 0);

  // historial de precios (cartera + universo + benchmark)
  const histTk = [...new Set([...positionsAll.map((p) => p.ticker), ...universe, BENCH])];
  const priceHistory: Record<string, { as_of: string; close: number }[]> = {};
  for (const t of histTk) {
    const rows = await get("price_history", { select: "as_of,close", ticker: `eq.${t}`, order: "as_of" });
    priceHistory[t] = rows.map((b: any) => ({ as_of: b.as_of, close: Number(b.close) }));
  }

  const valuation: Record<string, Adv3Valuation> = {};
  const candidates: ScanCandidate[] = [];
  const sectorOf = (t: string) => instruments[t]?.sector ?? (scan.find((s: any) => String(s.ticker).toUpperCase() === t)?.sector ?? null);
  for (const t of universe) {
    const cv = fv[t]; const prod = modelMargin(cv, "DCF_productivo"); const giic = modelMargin(cv, "FCFF_GIIC");
    valuation[t] = { productiveMargin: prod.m, productiveConfidence: prod.m != null ? "media" : null, fcffMargin: giic.m, fcffConfidence: (giic.c as any) ?? null, priceComparable: true };
    const sector = sectorOf(t); const ac = instruments[t]?.asset_class ?? null;
    candidates.push({ ticker: t, name: instruments[t]?.name ?? null, sector, country: null, currency: instruments[t]?.currency ?? null, assetClass: ac, kind: kindOf(ac, sector), inPortfolio: ptk.includes(t), composite: scan.find((s: any) => String(s.ticker).toUpperCase() === t)?.composite ?? null });
  }
  const input: ScanInput = {
    candidates, valuation, fundamentals,
    portfolio: {
      positions: positionsAll.map((p) => ({ ticker: p.ticker, name: p.name, sector: instruments[p.ticker]?.sector ?? null, country: null, currency: p.currency, assetClass: p.asset_class, marketValue: p.marketValue ?? 0, weight: total > 0 ? (p.marketValue ?? 0) / total : 0 })),
      cash: 0,
    },
    priceHistory, contributions: [CONTRIB],
    constraints: { maxPositionWeight: 0.45, maxSectorWeight: 0.50, minMarginToBuy: 0.10 },
    fcffFallback: FF_VALPOLICY,
  };

  const report = buildScanner(input);
  const plan = buildAllocationPlan(input, report, CONTRIB);
  const emittedAt = new Date().toISOString();
  const rec = buildDecisionRecord({ input, report, plan, benchmark: BENCH, algoVersion: "P2.6", featureFlags: { VITE_FF_VALPOLICY: FF_VALPOLICY }, emittedAt });

  const today = emittedAt.slice(0, 10);
  await post("pit_snapshots", [{
    kind: "decision_record", ticker: rec.decisionId, observation_date: today, published_at: today,
    snapshot_date: today, captured_at: emittedAt, source: "P2.6", data_version: today, payload: rec,
  }], "kind,ticker,observation_date,snapshot_date");

  console.log(JSON.stringify({
    ok: true, decisionId: rec.decisionId, emittedAt, chosen: rec.chosen,
    recomendaciones: rec.recommendations.map((l) => ({ ticker: l.ticker, monto: l.amount, margen: l.margin, conf: l.confidence })),
    riesgo: { antes: rec.riskBefore, despues: rec.riskAfter }, benchmark: rec.benchmark,
    universo: rec.universe, descartados: rec.discardedCandidates.map((d) => d.ticker),
  }, null, 2));
}

main().catch((e) => { console.error(e); process.exit(1); });
