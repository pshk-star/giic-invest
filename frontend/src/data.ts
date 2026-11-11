// Acceso a datos vía Supabase (con RLS). La cartera es privada por usuario;
// mercado y scanner son de solo lectura para autenticados.
import { supabase } from "./lib/supabase";
import type { ETFHolding, Position, PriceInfo } from "./core/analytics";
import type { InstrumentMeta, Split, Txn } from "./core/portfolio-tx";
import type { FundamentalsPayload } from "./core/valuation";

export interface InstrumentRow {
  ticker: string;
  name: string | null;
  asset_class: string | null;
  exchange: string | null;
  currency: string | null;
  status: string | null;
}

export async function getTransactions(): Promise<Txn[]> {
  const { data, error } = await supabase
    .from("transactions").select("*").order("executed_at", { ascending: true });
  if (error) throw error;
  return (data ?? []) as Txn[];
}

export async function addTransaction(t: Partial<Txn>): Promise<void> {
  const { error } = await supabase.from("transactions").insert(t);
  if (error) throw error;
}

export async function deleteTransaction(id: string): Promise<void> {
  const { error } = await supabase.from("transactions").delete().eq("id", id);
  if (error) throw error;
}

export async function searchInstruments(query: string): Promise<InstrumentRow[]> {
  // Sanea la entrada: PostgREST interpreta , ( ) * en el filtro `.or()`. Dejamos solo
  // caracteres válidos de ticker/nombre para evitar romper la consulta.
  const q = query.trim().replace(/[(),*%]/g, "").slice(0, 40);
  if (!q) return [];
  const qu = q.toUpperCase();
  // Prioriza coincidencia por prefijo de ticker (lo más común) y por nombre.
  const { data, error } = await supabase
    .from("instruments")
    .select("ticker,name,asset_class,exchange,currency,status")
    .or(`ticker.ilike.${qu}%,name.ilike.%${q}%`)
    .order("ticker")
    .limit(20);
  if (error) throw error;
  return (data ?? []) as InstrumentRow[];
}

export interface InstrumentIdentity {
  ticker: string;
  country_issuer: string | null;
  country_listing: string | null;
  quote_currency: string | null;
  report_currency: string | null;
  instrument_type: string | null;
  adr_ratio: number | null;
  cik: string | null;
  figi: string | null;
  isin: string | null;
  lei: string | null;
  identity: Record<string, { value: unknown; source: string | null; as_of: string | null; status: string }> | null;
  identity_as_of: string | null;
}

// Lee la identidad persistida (columnas de 0012). Seguro: si las columnas aún no
// existen (migración no aplicada en ese entorno), devuelve {} y la UI usa su derivación.
export async function getInstrumentIdentity(tickers: string[]): Promise<Record<string, InstrumentIdentity>> {
  if (tickers.length === 0) return {};
  try {
    const { data, error } = await supabase.from("instruments")
      .select("ticker,country_issuer,country_listing,quote_currency,report_currency,instrument_type,adr_ratio,cik,figi,isin,lei,identity,identity_as_of")
      .in("ticker", tickers.map((t) => t.toUpperCase()));
    if (error || !data) return {};
    const out: Record<string, InstrumentIdentity> = {};
    for (const r of data) out[r.ticker] = r as InstrumentIdentity;
    return out;
  } catch {
    return {};
  }
}

export async function getInstruments(tickers: string[]): Promise<Record<string, InstrumentMeta>> {
  if (tickers.length === 0) return {};
  const { data, error } = await supabase
    .from("instruments").select("ticker,name,asset_class,status,currency,sector,exchange").in("ticker", tickers);
  if (error) throw error;
  const out: Record<string, InstrumentMeta> = {};
  for (const r of data ?? [])
    out[r.ticker] = { name: r.name, asset_class: r.asset_class, status: r.status,
                      currency: r.currency, sector: r.sector, exchange: r.exchange };
  return out;
}

export interface Settings {
  base_currency: string;
  capital_available: number;
  monthly_contribution: number;
  risk_tolerance: string;
  horizon_years: number;
  max_weight_per_asset: number;
  max_weight_per_sector: number;
  min_cash: number;
}

export async function getSettings(): Promise<Settings | null> {
  const { data, error } = await supabase.from("settings").select("*").limit(1);
  if (error) throw error;
  return (data?.[0] as Settings) ?? null;
}

export async function saveSettings(s: Partial<Settings>): Promise<void> {
  // upsert de la fila única del usuario (user_id lo pone el default auth.uid()).
  const { error } = await supabase.from("settings").upsert(s, { onConflict: "user_id" });
  if (error) throw error;
}

export interface QuoteRow {
  ticker: string;
  price: number;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  day_high: number | null;
  day_low: number | null;
  volume: number | null;
  currency: string;
  exchange: string | null;
  market_state: string | null;
  quote_time: string;
  source: string;
  delayed: boolean;
  updated_at: string;
}

export async function getQuotes(tickers: string[]): Promise<Record<string, QuoteRow>> {
  if (tickers.length === 0) return {};
  const { data, error } = await supabase.from("quotes").select("*").in("ticker", tickers);
  if (error) throw error;
  const out: Record<string, QuoteRow> = {};
  for (const r of data ?? []) out[r.ticker] = r as QuoteRow;
  return out;
}

export interface PriceBar { as_of: string; close: number; volume: number | null; adjusted?: boolean | null; }

export async function getPriceHistory(ticker: string, fromISO?: string): Promise<PriceBar[]> {
  // Trae el historial COMPLETO paginando (el servidor topa ~1000 filas por página),
  // en orden ascendente. Sin cortes accidentales: se recorren todas las páginas.
  const PAGE = 1000;
  const out: PriceBar[] = [];
  for (let offset = 0; ; offset += PAGE) {
    let q = supabase.from("price_history").select("as_of,close,volume,adjusted")
      .eq("ticker", ticker.toUpperCase()).order("as_of", { ascending: true }).range(offset, offset + PAGE - 1);
    if (fromISO) q = q.gte("as_of", fromISO);
    const { data, error } = await q;
    if (error) throw error;
    const batch = data ?? [];
    for (const r of batch) out.push({ as_of: r.as_of, close: Number(r.close), volume: r.volume != null ? Number(r.volume) : null, adjusted: r.adjusted ?? null });
    if (batch.length < PAGE) break;
  }
  return out;
}

export async function getCorporateActions(tickers: string[]): Promise<Split[]> {
  if (tickers.length === 0) return [];
  const { data, error } = await supabase
    .from("corporate_actions").select("ticker,ratio,ex_date").in("ticker", tickers);
  if (error) throw error;
  return (data ?? []).map((r) => ({ ticker: r.ticker, ratio: Number(r.ratio), ex_date: r.ex_date }));
}

export async function getFundamentals(tickers: string[]): Promise<Record<string, FundamentalsPayload>> {
  if (tickers.length === 0) return {};
  const { data, error } = await supabase.from("fundamentals").select("ticker,payload").in("ticker", tickers);
  if (error) throw error;
  const out: Record<string, FundamentalsPayload> = {};
  for (const r of data ?? []) out[r.ticker] = (r.payload ?? {}) as FundamentalsPayload;
  return out;
}

export interface ScanRow {
  run_id: string;
  as_of: string;
  ticker: string;
  rank: number;
  composite: number;
  factor_value: number | null;
  factor_quality: number | null;
  factor_growth: number | null;
  factor_momentum: number | null;
  factor_low_risk: number | null;
  tags: string[] | null;
  sector: string | null;
  is_sample: boolean;
}

export async function getPositions(): Promise<Position[]> {
  const { data, error } = await supabase.from("positions").select("*").order("ticker");
  if (error) throw error;
  return (data ?? []) as Position[];
}

export async function addPosition(p: Partial<Position>): Promise<void> {
  const { error } = await supabase.from("positions").insert(p);
  if (error) throw error;
}

export async function deletePosition(id: string): Promise<void> {
  const { error } = await supabase.from("positions").delete().eq("id", id);
  if (error) throw error;
}

export async function getPrices(tickers: string[]): Promise<Record<string, PriceInfo>> {
  if (tickers.length === 0) return {};
  const { data, error } = await supabase.from("prices").select("*").in("ticker", tickers);
  if (error) throw error;
  const out: Record<string, PriceInfo> = {};
  for (const r of data ?? []) out[r.ticker] = { close: r.close, as_of: r.as_of, currency: r.currency };
  return out;
}

// ---- Predicciones del modelo (laboratorio) — SOLO LECTURA ----
export interface PredictionRow {
  model_name: string;
  model_version: string;
  horizon_sessions: number;
  as_of: string;
  evaluate_on: string;
  ticker: string;
  benchmark: string | null;
  emitted_at: string | null;
  prediction: { rel_return?: number; pct_rank?: number; n_cross_section?: number } | null;
  data_ref: { status?: string; feature_set?: string; features_version?: string } | null;
}

export async function getPredictions(): Promise<PredictionRow[]> {
  const { data, error } = await supabase
    .from("predictions")
    .select("model_name,model_version,horizon_sessions,as_of,evaluate_on,ticker,benchmark,emitted_at,prediction,data_ref")
    .eq("origin", "production")
    .order("as_of", { ascending: false });
  if (error) throw error;
  return (data ?? []) as PredictionRow[];
}

export async function getPredictionsByTicker(ticker: string): Promise<PredictionRow[]> {
  const { data, error } = await supabase
    .from("predictions")
    .select("model_name,model_version,horizon_sessions,as_of,evaluate_on,ticker,benchmark,emitted_at,prediction,data_ref")
    .eq("origin", "production").eq("ticker", ticker.toUpperCase())
    .order("horizon_sessions", { ascending: true });
  if (error) throw error;
  return (data ?? []) as PredictionRow[];
}

// ---- Fondos Fintual (requiere migración 0009; degrada a vacío si aún no existe) ----
export interface FundRow {
  id: string; symbol: string; name: string | null; provider: string; currency: string; archived: boolean;
}
export async function getFunds(): Promise<FundRow[]> {
  const { data, error } = await supabase
    .from("user_funds").select("id,symbol,name,provider,currency,archived")
    .eq("archived", false).order("symbol");
  if (error) return []; // tabla aún no creada (migración pendiente) -> vacío
  return (data ?? []) as FundRow[];
}
export async function addFund(f: { symbol: string; name?: string; currency: string; provider?: string }): Promise<void> {
  const { error } = await supabase.from("user_funds").insert({
    symbol: f.symbol.toUpperCase().trim(), name: f.name ?? null,
    currency: f.currency, provider: f.provider ?? "fintual",
  });
  if (error) throw error;
}
export async function archiveFund(id: string): Promise<void> {
  const { error } = await supabase.from("user_funds").update({ archived: true }).eq("id", id);
  if (error) throw error;
}
export interface FundNavRow { fund_id: string; as_of: string; nav: number; currency: string; }
export async function getFundNavs(): Promise<FundNavRow[]> {
  const { data, error } = await supabase
    .from("fund_navs").select("fund_id,as_of,nav,currency").order("as_of", { ascending: false });
  if (error) return [];
  return (data ?? []).map((r) => ({ fund_id: r.fund_id, as_of: r.as_of, nav: Number(r.nav), currency: r.currency }));
}
export async function addFundNav(n: { fund_id: string; as_of: string; nav: number; currency: string }): Promise<void> {
  const { error } = await supabase.from("fund_navs").upsert(n, { onConflict: "fund_id,as_of" });
  if (error) throw error;
}

export interface OutcomeRow {
  prediction_id: number;
  realized_return: number | null;
  benchmark_return: number | null;
  outperformed: boolean | null;
  evaluated_at: string;
}

export async function getPredictionOutcomes(): Promise<OutcomeRow[]> {
  const { data, error } = await supabase
    .from("prediction_outcomes")
    .select("prediction_id,realized_return,benchmark_return,outperformed,evaluated_at");
  if (error) throw error;
  return (data ?? []) as OutcomeRow[];
}

// ---- Portfolio X-Ray: último snapshot 'complete' por ETF + sus líneas ----
export interface XraySnapshot {
  etf: string; provider: string; as_of: string; equity_pct: number | null;
  status: string; n_lines: number | null; weight_sum: number | null; source: "auto" | "manual";
}
export interface XrayWeightRow {
  etf: string; ticker: string | null; name: string | null; weight: number | null;
  asset_class: string; company_key: string | null; sector?: string | null;
}
export type ImportStatus = "complete" | "partial" | "failed";
// Registra una importación: snapshot de estado (user_etf_imports) + líneas (user_etf_holdings).
// Idempotente: reimportar el mismo archivo no duplica (upsert por clave de línea).
export async function addUserEtfImport(p: {
  etf: string; as_of: string; status: ImportStatus; n_lines: number;
  weight_sum: number; source_file: string; lines: Record<string, unknown>[];
}): Promise<void> {
  const s = await supabase.from("user_etf_imports").upsert(
    { etf: p.etf, as_of: p.as_of, status: p.status, n_lines: p.n_lines,
      weight_sum: p.weight_sum, source_file: p.source_file },
    { onConflict: "user_id,etf,as_of" });
  if (s.error) throw s.error;
  if (p.lines.length) {
    const h = await supabase.from("user_etf_holdings")
      .upsert(p.lines, { onConflict: "user_id,etf,as_of,line_key", ignoreDuplicates: true });
    if (h.error) throw h.error;
  }
}

// Solo importaciones COMPLETAS y validadas; la más reciente por ETF. Las parcial/fallida se
// ignoran aquí (nunca reemplazan la última válida).
interface ManualMeta { as_of: string; rows: XrayWeightRow[]; n_lines: number | null; weight_sum: number | null; }
async function userHoldingsLatest(etfs: string[]): Promise<Map<string, ManualMeta>> {
  const out = new Map<string, ManualMeta>();
  const imp = await supabase.from("user_etf_imports")
    .select("etf,as_of,status,n_lines,weight_sum").eq("status", "complete").order("as_of", { ascending: false });
  if (imp.error) return out; // 0011 aún no aplicada
  const up = etfs.map((e) => e.toUpperCase());
  const chosen = new Map<string, { as_of: string; n_lines: number | null; weight_sum: number | null }>();
  for (const r of imp.data ?? []) {
    const e = (r.etf as string).toUpperCase();
    if (up.includes(e) && !chosen.has(e)) chosen.set(e, { as_of: r.as_of, n_lines: r.n_lines, weight_sum: r.weight_sum });
  }
  for (const [e, m] of chosen) {
    const { data } = await supabase.from("user_etf_holdings")
      .select("etf,ticker,name,weight,asset_class,company_key,sector").eq("etf", e).eq("as_of", m.as_of);
    out.set(e, { as_of: m.as_of, n_lines: m.n_lines, weight_sum: m.weight_sum,
      rows: (data ?? []).map((r) => ({ etf: e, ticker: r.ticker, name: r.name,
        weight: r.weight != null ? Number(r.weight) : null, asset_class: r.asset_class,
        company_key: r.company_key, sector: r.sector })) });
  }
  return out;
}

export async function getXrayData(etfs: string[]): Promise<{ snapshots: XraySnapshot[]; weights: XrayWeightRow[] }> {
  if (etfs.length === 0) return { snapshots: [], weights: [] };
  const up = etfs.map((x) => x.toUpperCase());
  // automático: último snapshot 'complete' por etf
  const autoLatest = new Map<string, XraySnapshot>();
  const snapQ = await supabase.from("etf_snapshots")
    .select("etf,provider,as_of,status,equity_pct,n_lines,weight_sum").eq("status", "complete")
    .order("as_of", { ascending: false });
  if (!snapQ.error) {
    for (const s of snapQ.data ?? []) {
      const e = (s.etf as string).toUpperCase();
      if (up.includes(e) && !autoLatest.has(e)) autoLatest.set(e, { etf: e, provider: s.provider, as_of: s.as_of,
        equity_pct: s.equity_pct, status: s.status, n_lines: s.n_lines, weight_sum: s.weight_sum, source: "auto" });
    }
  }
  const manual = await userHoldingsLatest(etfs);

  const snapshots: XraySnapshot[] = [];
  const weights: XrayWeightRow[] = [];
  for (const e of up) {
    const a = autoLatest.get(e), m = manual.get(e);
    const useManual = m && (!a || m.as_of >= a.as_of);
    if (useManual && m) {
      snapshots.push({ etf: e, provider: "manual", as_of: m.as_of, equity_pct: null,
        status: "complete", n_lines: m.n_lines, weight_sum: m.weight_sum, source: "manual" });
      weights.push(...m.rows);
    } else if (a) {
      snapshots.push(a);
      const { data } = await supabase.from("etf_holdings")
        .select("etf,ticker,name,weight,asset_class,company_key,sector")
        .eq("etf", a.etf).eq("provider", a.provider).eq("as_of", a.as_of);
      for (const r of data ?? []) weights.push({ etf: r.etf, ticker: r.ticker, name: r.name,
        weight: r.weight != null ? Number(r.weight) : null, asset_class: r.asset_class,
        company_key: r.company_key, sector: r.sector });
    }
  }
  return { snapshots, weights };
}

export async function getEtfHoldings(etfs: string[]): Promise<Record<string, ETFHolding[]>> {
  if (etfs.length === 0) return {};
  const { data, error } = await supabase.from("etf_holdings").select("*").in("etf", etfs);
  if (error) throw error;
  const out: Record<string, ETFHolding[]> = {};
  for (const r of data ?? []) {
    (out[r.etf] ??= []).push({ ticker: r.ticker, weight: r.weight });
  }
  return out;
}

export async function getFxRates(base: string): Promise<Record<string, number>> {
  const { data, error } = await supabase.from("fx_rates").select("*").eq("base", base);
  if (error) throw error;
  const out: Record<string, number> = { [base]: 1 };
  for (const r of data ?? []) out[r.currency] = r.rate;
  return out;
}

export async function getLatestScan(): Promise<ScanRow[]> {
  const { data, error } = await supabase.from("v_latest_scan").select("*").order("rank");
  if (error) throw error;
  return (data ?? []) as ScanRow[];
}

export async function getLatestRun(): Promise<any | null> {
  // Solo corridas COMPLETADAS (publicación atómica): nunca mostramos datos a medias.
  const { data, error } = await supabase
    .from("scan_runs").select("*")
    .eq("status", "completed")
    .order("completed_at", { ascending: false })
    .limit(1);
  if (error) throw error;
  return data?.[0] ?? null;
}

// P1.9 — Valoración fundamental (experimental). El payload lo calcula el backend y se guarda en
// pit_snapshots (kind='fundamental_valuation'); aquí se lee el snapshot MÁS RECIENTE por ticker y
// se renderiza tal cual (sin recálculo en el frontend).
export async function getFundamentalValuations(): Promise<import("./core/fundval").FundValPayload> {
  const { data, error } = await supabase
    .from("pit_snapshots").select("ticker,snapshot_date,observation_date,captured_at,payload")
    .eq("kind", "fundamental_valuation")
    .order("snapshot_date", { ascending: false })
    .order("captured_at", { ascending: false });   // en empate de día, gana la captura más reciente (valores corregidos)
  if (error) throw error;
  const resultados: Record<string, import("./core/fundval").CompanyValuation> = {};
  let generado: string | undefined;
  for (const r of (data ?? []) as any[]) {
    if (!resultados[r.ticker]) {            // primer visto = captura más reciente
      resultados[r.ticker] = r.payload;
      generado = generado ?? r.observation_date ?? r.snapshot_date;
    }
  }
  return { resultados, generado, no_calibrado_a_mercado: true };
}
