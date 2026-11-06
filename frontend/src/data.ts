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
