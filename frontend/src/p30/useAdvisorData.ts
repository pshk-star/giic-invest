// P3.0 — Carga ÚNICA de datos reales + construcción de la recomendación reutilizando el MOTOR existente
// (buildUnifiedAdvisor). No duplica ni crea lógica financiera: arma el ScanInput desde las fuentes de
// GIIC igual que la pantalla /asesor y expone el bundle para Inicio, Oportunidades y la ficha. Los
// componentes visuales SOLO leen de aquí; no calculan valoraciones, riesgo ni recomendaciones.
import { useEffect, useState } from "react";
import {
  getTransactions, getInstruments, getCorporateActions, getPrices, getPriceHistory,
  getFundamentalValuations, getFundamentals, getLatestScan, getXrayData, getSettings,
} from "../data";
import { derivePositions, type DerivedPosition } from "../core/portfolio-tx";
import { buildUnifiedAdvisor, type AdvisorReport, type EtfInfo } from "../core/advisor-engine";
import { profileFromSettings, missingEssentials, type Profile } from "../core/advisor-profile";
import type { ScanInput, ScanCandidate, InstrumentKind } from "../core/opportunity-scanner";
import type { Adv3Valuation } from "../core/advisor3";
import type { CompanyValuation } from "../core/fundval";

const ETF = ["etf", "fund", "etn", "mutualfund"];
function kindOf(ac: string | null | undefined, sector: string | null | undefined): InstrumentKind {
  const a = (ac ?? "").toLowerCase();
  if (ETF.includes(a)) return "etf";
  if (/financ|bank|banco|insurance|seguro/i.test(sector ?? "")) return "banco";
  if (a && !["equity", "stock", "adr", "common"].includes(a)) return "otro";
  return "empresa";
}
function modelMargin(cv: CompanyValuation | undefined, m: string): { m: number | null; c: string | null } {
  const b = cv?.modelos.find((x) => x.modelo === m);
  if (!b || b.disponible === false || b.margen_seguridad_pct == null) return { m: null, c: null };
  return { m: b.margen_seguridad_pct / 100, c: b.confianza ?? null };
}

export interface AdvisorData {
  loading: boolean;
  err: string | null;
  missing: string[] | null;                 // datos de perfil faltantes (no se inventan)
  profile: Profile | null;
  report: AdvisorReport | null;
  positions: DerivedPosition[];
  priceHistory: Record<string, { as_of: string; close: number }[]>;
  fv: Record<string, CompanyValuation>;     // valoraciones por ticker (para la ficha)
  fundamentals: Record<string, any>;        // fundamentales por ticker (para la ficha)
  prices: Record<string, { close?: number | null; currency?: string | null; as_of?: string } & any>;
  instruments: Record<string, any>;
  etfInfo: Record<string, EtfInfo>;         // rol/solapamiento/equity_pct por ETF (X-ray)
  scanInput: ScanInput | null;              // insumo del motor, para recomputar asignación con otro aporte
  reload: () => void;
}

export function useAdvisorData(): AdvisorData {
  const [state, setState] = useState<Omit<AdvisorData, "reload">>({
    loading: true, err: null, missing: null, profile: null, report: null,
    positions: [], priceHistory: {}, fv: {}, fundamentals: {}, prices: {}, instruments: {},
    etfInfo: {}, scanInput: null,
  });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setState((s) => ({ ...s, loading: true, err: null }));
      try {
        const settings = await getSettings();
        const profile: Profile = profileFromSettings(settings);
        const miss = missingEssentials(profile);
        if (miss.length) { if (!cancelled) setState((s) => ({ ...s, loading: false, missing: miss, profile, report: null })); return; }

        const txns = await getTransactions();
        const ptk = [...new Set(txns.map((t) => t.ticker.toUpperCase()))];
        const [scan, fvPayload] = await Promise.all([getLatestScan().catch(() => []), getFundamentalValuations()]);
        const fv = fvPayload.resultados;
        const universe = [...new Set([...ptk, ...scan.map((s) => s.ticker.toUpperCase()), ...Object.keys(fv)])];
        const [instruments, prices, splits, fundamentals] = await Promise.all([
          getInstruments(universe), getPrices(universe), getCorporateActions(ptk), getFundamentals(universe),
        ]);
        const positionsAll = derivePositions(txns, prices, instruments, splits).filter((p) => (p.marketValue ?? 0) > 0);
        const total = positionsAll.reduce((s, p) => s + (p.marketValue ?? 0), 0);

        const histTk = [...new Set([...positionsAll.map((p) => p.ticker), ...universe])];
        const histArr = await Promise.all(histTk.map((t) => getPriceHistory(t).catch(() => [])));
        const priceHistory: Record<string, { as_of: string; close: number }[]> = {};
        histTk.forEach((t, i) => { priceHistory[t] = histArr[i].map((b) => ({ as_of: b.as_of, close: Number(b.close) })); });

        const etfHeld = positionsAll.filter((p) => ETF.includes((p.asset_class ?? "").toLowerCase())).map((p) => p.ticker);
        const xray = etfHeld.length ? await getXrayData(etfHeld).catch(() => ({ weights: [] as any[], snapshots: [] as any[] })) : { weights: [] as any[], snapshots: [] as any[] };
        const etfLookthrough: Record<string, Record<string, number>> = {};
        for (const w of xray.weights) { if (!w.ticker || w.weight == null) continue; (etfLookthrough[w.etf] ??= {})[String(w.ticker).toUpperCase()] = w.weight > 1 ? w.weight / 100 : w.weight; }
        const directHeld = new Set(positionsAll.filter((p) => !ETF.includes((p.asset_class ?? "").toLowerCase())).map((p) => p.ticker.toUpperCase()));
        const etfInfo: Record<string, EtfInfo> = {};
        for (const etf of etfHeld) {
          const snap = (xray.snapshots ?? []).find((s: any) => s.etf === etf);
          const rows = xray.weights.filter((w: any) => w.etf === etf);
          const equityPct = snap?.equity_pct ?? null;
          const role: EtfInfo["role"] = (rows.length === 0 || (equityPct != null && equityPct < 0.2)) ? "commodity" : "equity_amplio";
          let overlap = 0;
          for (const w of rows) if (w.ticker && directHeld.has(String(w.ticker).toUpperCase())) overlap += (w.weight > 1 ? w.weight / 100 : w.weight);
          etfInfo[etf] = { role, overlapPct: overlap, equityPct };
        }

        const valuation: Record<string, Adv3Valuation> = {};
        const candidates: ScanCandidate[] = [];
        const sectorOf = (t: string) => instruments[t]?.sector ?? (scan.find((s) => s.ticker.toUpperCase() === t)?.sector ?? null);
        for (const t of universe) {
          const cv = fv[t]; const prod = modelMargin(cv, "DCF_productivo"); const giic = modelMargin(cv, "FCFF_GIIC");
          const giicB = cv?.modelos.find((x) => x.modelo === "FCFF_GIIC");
          valuation[t] = { productiveMargin: prod.m, productiveConfidence: prod.m != null ? "media" : null, fcffMargin: giic.m, fcffConfidence: (giic.c as any) ?? null, priceComparable: true,
            reviewBlock: !!giicB?.review_block, reviewReason: (giicB?.review_reasons ?? []).join("; ") || null };
          const sector = sectorOf(t); const ac = instruments[t]?.asset_class ?? null;
          candidates.push({ ticker: t, name: instruments[t]?.name ?? null, sector, country: null, currency: instruments[t]?.currency ?? null, assetClass: ac, kind: kindOf(ac, sector), inPortfolio: ptk.includes(t), composite: scan.find((s) => s.ticker.toUpperCase() === t)?.composite ?? null });
        }
        const scanInput: ScanInput = {
          candidates, valuation, fundamentals: {},
          portfolio: { positions: positionsAll.map((p) => ({ ticker: p.ticker, name: p.name, sector: instruments[p.ticker]?.sector ?? null, country: null, currency: p.currency, assetClass: p.asset_class, marketValue: p.marketValue ?? 0, weight: total > 0 ? (p.marketValue ?? 0) / total : 0 })), cash: profile.capitalAvailable ?? 0 },
          priceHistory, etfLookthrough, contributions: [1000], constraints: { maxPositionWeight: 0.45, maxSectorWeight: 0.50, minMarginToBuy: 0.10 },
          fcffFallback: import.meta.env.VITE_FF_VALPOLICY === "1",
        };
        const report = buildUnifiedAdvisor({ profile, scanInput, etfInfo });
        if (!cancelled) setState({ loading: false, err: null, missing: null, profile, report, positions: positionsAll, priceHistory, fv, fundamentals, prices, instruments, etfInfo, scanInput });
      } catch (e) {
        if (!cancelled) setState((s) => ({ ...s, loading: false, err: String(e) }));
      }
    })();
    return () => { cancelled = true; };
  }, [tick]);

  return { ...state, reload: () => setTick((t) => t + 1) };
}
