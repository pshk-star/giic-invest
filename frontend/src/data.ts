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

export interface PriceBar { as_of: string; close: number; volume: number | null; }

export async function getPriceHistory(ticker: string, fromISO?: string): Promise<PriceBar[]> {
  // Orden DESC + límite para traer lo más RECIENTE (el servidor topa ~1000 filas);
  // luego se invierte a orden ascendente para graficar.
  let q = supabase.from("price_history").select("as_of,close,volume")
    .eq("ticker", ticker.toUpperCase()).order("as_of", { ascending: false }).limit(1000);
  if (fromISO) q = q.gte("as_of", fromISO);
  const { data, error } = await q;
  if (error) throw error;
  return (data ?? [])
    .map((r) => ({ as_of: r.as_of, close: Number(r.close), volume: r.volume != null ? Number(r.volume) : null }))
    .reverse();
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
