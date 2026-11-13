import { valuationInput } from "../core/valuation-feed";
// Etapa A — Investment Advisor UNIFICADO (EXPERIMENTAL, flag VITE_FF_UNIFIED). Pantalla principal que
// RECOMIENDA automáticamente: qué hacer con cada posición, qué comprar con dinero nuevo, cuánto,
// oportunidades, riesgos y por qué. Sin parámetros manuales: todo viene del PERFIL. Reutiliza el
// orquestador advisor-engine (que compone Scanner + Advisor 3.0 + asignación + política). No ejecuta
// operaciones; recomendaciones SIMULADAS.
import { useEffect, useState } from "react";
import { Panel } from "../components/Panel";
import {
  getTransactions, getInstruments, getCorporateActions, getPrices, getPriceHistory,
  getFundamentalValuations, getFundamentals, getLatestScan, getXrayData, getSettings, saveSettings, type Settings,
} from "../data";
import { derivePositions } from "../core/portfolio-tx";
import { buildUnifiedAdvisor, type AdvisorReport, type PositionAction, type EtfInfo } from "../core/advisor-engine";
import { profileFromSettings, missingEssentials, type Profile } from "../core/advisor-profile";
import type { ScanInput, ScanCandidate, InstrumentKind } from "../core/opportunity-scanner";
import type { Adv3Valuation } from "../core/advisor3";
import { money, pct } from "../format";

const ETF = ["etf", "fund", "etn", "mutualfund"];
function kindOf(ac: string | null | undefined, sector: string | null | undefined): InstrumentKind {
  const a = (ac ?? "").toLowerCase();
  if (ETF.includes(a)) return "etf";
  if (/financ|bank|banco|insurance|seguro/i.test(sector ?? "")) return "banco";
  if (a && !["equity", "stock", "adr", "common"].includes(a)) return "otro";
  return "empresa";
}

const actionTone = (a: PositionAction) => a === "VENDER" ? "text-term-crit" : a === "REDUCIR" ? "text-term-warn"
  : a === "REVISAR" ? "text-term-info" : a === "ACUMULAR" ? "text-term-accent" : "text-term-muted";
const classLabel: Record<string, string> = { compra_recomendada: "Compra recomendada", oportunidad_analizada: "Oportunidad analizada", candidata_investigacion: "Candidata de investigación", poco_atractiva: "Poco atractiva", evidencia_insuficiente: "Evidencia insuficiente" };

export function UnifiedAdvisor() {
  const [report, setReport] = useState<AdvisorReport | null>(null);
  const [missing, setMissing] = useState<string[] | null>(null);
  const [form, setForm] = useState<Partial<Settings>>({ base_currency: "USD", risk_tolerance: "moderado" });
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true); setErr(null);
    try {
      const settings = await getSettings();
      const profile: Profile = profileFromSettings(settings);
      const miss = missingEssentials(profile);
      if (miss.length) { setMissing(miss); if (settings) setForm(settings); setReport(null); return; }
      setMissing(null);

      const txns = await getTransactions();
      const ptk = [...new Set(txns.map((t) => t.ticker.toUpperCase()))];
      const [scan, fv] = await Promise.all([getLatestScan().catch(() => []), getFundamentalValuations()]);
      const universe = [...new Set([...ptk, ...scan.map((s) => s.ticker.toUpperCase()), ...Object.keys(fv.resultados)])];
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
      // política de ETF: rol (equity vs commodity), solapamiento con posiciones directas
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
      const scanFund: Record<string, any> = {};
      const candidates: ScanCandidate[] = [];
      const sectorOf = (t: string) => instruments[t]?.sector ?? (scan.find((s) => s.ticker.toUpperCase() === t)?.sector ?? null);
      for (const t of universe) {
        const cv = fv.resultados[t];

        valuation[t] = valuationInput(cv);
        const f = fundamentals[t] as any;
        scanFund[t] = { roic: f?.roic ?? null, revGrowth: f?.rev_growth_yoy ?? null, netMargin: f?.net_margin ?? null, operatingMargin: f?.operating_margin ?? null, fcfTtm: f?.fcf_ttm ?? null };
        const sector = sectorOf(t); const ac = instruments[t]?.asset_class ?? null;
        candidates.push({ ticker: t, name: instruments[t]?.name ?? null, sector, country: null, currency: instruments[t]?.currency ?? null, assetClass: ac, kind: kindOf(ac, sector), inPortfolio: ptk.includes(t), composite: scan.find((s) => s.ticker.toUpperCase() === t)?.composite ?? null });
      }
      const scanInput: ScanInput = {
        methodologyValidated: Object.values(valuation).length > 0 && Object.values(valuation).every(v => v.engineMethodologyValidated === true),
        candidates, valuation, fundamentals: scanFund,
        portfolio: { positions: positionsAll.map((p) => ({ ticker: p.ticker, name: p.name, sector: instruments[p.ticker]?.sector ?? null, country: null, currency: p.currency, assetClass: p.asset_class, marketValue: p.marketValue ?? 0, weight: total > 0 ? (p.marketValue ?? 0) / total : 0 })), cash: profile.capitalAvailable ?? 0 },
        priceHistory, etfLookthrough, contributions: [1000], constraints: { maxPositionWeight: 0.45, maxSectorWeight: 0.50, minMarginToBuy: 0.10 },
        fcffFallback: import.meta.env.VITE_FF_VALPOLICY === "1",
      };
      setReport(buildUnifiedAdvisor({ profile, scanInput, etfInfo }));
    } catch (e) { setErr(String(e)); } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function saveProfile() {
    setLoading(true);
    try { await saveSettings(form); await load(); } catch (e) { setErr(String(e)); setLoading(false); }
  }

  if (loading) return <div className="p-8 text-term-muted">Calculando recomendación…</div>;
  if (err) return <div className="p-8 text-rose-400">Error: {err}</div>;

  if (missing) return (
    <div className="p-4 md:p-6 max-w-lg">
      <Panel title="Configura tu perfil (una sola vez)">
        <div className="text-xs text-term-muted mb-3">Faltan datos esenciales: <strong>{missing.join(", ")}</strong>. GIIC no inventa estos valores; configúralos una vez y los análisis correrán automáticamente.</div>
        <div className="space-y-2 text-sm">
          <label className="flex justify-between gap-2">Moneda base <input value={form.base_currency ?? ""} onChange={(e) => setForm({ ...form, base_currency: e.target.value })} className="w-32 bg-term-panel2 border border-term-border rounded px-2 py-1" /></label>
          <label className="flex justify-between gap-2">Capital disponible <input type="number" value={form.capital_available ?? ""} onChange={(e) => setForm({ ...form, capital_available: Number(e.target.value) })} className="w-32 bg-term-panel2 border border-term-border rounded px-2 py-1" /></label>
          <label className="flex justify-between gap-2">Aporte mensual <input type="number" value={form.monthly_contribution ?? ""} onChange={(e) => setForm({ ...form, monthly_contribution: Number(e.target.value) })} className="w-32 bg-term-panel2 border border-term-border rounded px-2 py-1" /></label>
          <label className="flex justify-between gap-2">Efectivo mínimo <input type="number" value={form.min_cash ?? ""} onChange={(e) => setForm({ ...form, min_cash: Number(e.target.value) })} className="w-32 bg-term-panel2 border border-term-border rounded px-2 py-1" /></label>
          <label className="flex justify-between gap-2">Horizonte (años) <input type="number" value={form.horizon_years ?? ""} onChange={(e) => setForm({ ...form, horizon_years: Number(e.target.value) })} className="w-32 bg-term-panel2 border border-term-border rounded px-2 py-1" /></label>
          <label className="flex justify-between gap-2">Tolerancia al riesgo
            <select value={form.risk_tolerance ?? "moderado"} onChange={(e) => setForm({ ...form, risk_tolerance: e.target.value })} className="w-32 bg-term-panel2 border border-term-border rounded px-2 py-1">
              <option value="conservador">conservador</option><option value="moderado">moderado</option><option value="agresivo">agresivo</option>
            </select></label>
          <button onClick={saveProfile} className="mt-2 px-3 py-1 rounded bg-term-accent/20 border border-term-accent text-term-accent text-sm">Guardar y calcular</button>
        </div>
      </Panel>
    </div>
  );

  if (!report) return <div className="p-8 text-term-muted">Sin datos.</div>;
  const r = report;
  const ccy = r.currency;

  return (
    <div className="p-4 md:p-6 space-y-3">
      <div className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-200">
        <strong>Investment Advisor — experimental</strong> (Etapa A). Recomendaciones <strong>SIMULADAS</strong> (no ejecutadas), con el perfil gobernando los límites. Una sola decisión por instrumento.
      </div>

      {/* 1. Resumen ejecutivo */}
      <Panel title="1 · Qué recomienda GIIC hoy">
        <div className="text-sm">{r.executiveSummary}</div>
        <div className="text-[11px] text-term-muted mt-1">Postura: <strong>{r.posture}</strong> · topes {pct(r.constraintsUsed.maxPositionWeight)}/empresa, {pct(r.constraintsUsed.maxSectorWeight)}/sector ({r.constraintsUsed.sources.empresa}) · margen mínimo {pct(r.constraintsUsed.minMarginToBuy)}</div>
      </Panel>

      {/* 2. Acciones por posición */}
      <Panel title="2 · Acciones sobre tu cartera">
        <div className="space-y-1">
          {r.positions.map((p) => (
            <div key={p.ticker} className="text-xs flex items-baseline justify-between gap-2 border-b border-term-border/30 pb-1">
              <span><strong className={actionTone(p.action)}>{p.action}</strong>{p.trimPct ? ` −${Math.round(p.trimPct * 100)}%${p.trimAmount != null ? ` (${money(p.trimAmount, ccy)})` : ""}` : ""} · {p.ticker} <span className="text-term-muted">{p.name}</span></span>
              <span className="text-term-muted text-right">{p.margin != null ? `margen ${pct(p.margin)} (${p.source})` : "sin FV"} · peso {pct(p.weight)} · riesgo {pct(p.riskContribPct)}</span>
            </div>
          ))}
          {r.positions.map((p) => <div key={p.ticker + "-why"} className="text-[11px] text-term-muted">· {p.ticker}: {p.why}</div>)}
        </div>
      </Panel>

      {/* 3. Asignación de dinero nuevo */}
      <Panel title={`3 · Mejor uso de dinero nuevo (${money(r.newMoney.contribution, ccy)}) · ${r.newMoney.chosen}`}>
        {r.newMoney.legs.length ? (
          <div className="space-y-1 text-xs">
            {r.newMoney.legs.map((l) => (
              <div key={l.ticker}>{l.ticker} <strong>{money(l.amount, ccy)}</strong> → peso {pct(l.weightAfter)} <span className="text-term-muted">({l.reason})</span></div>
            ))}
            <div className="text-term-muted">Efectivo conservado: {money(r.newMoney.cashKept, ccy)} · vol {pct(r.newMoney.volBefore)} → {pct(r.newMoney.volAfter)}</div>
          </div>
        ) : <div className="text-xs text-term-muted">Mantener en efectivo.</div>}
        <div className="text-[11px] text-term-accent mt-2">{r.newMoney.why}</div>
      </Panel>

      {/* 4. Oportunidades */}
      <Panel title="4 · Principales oportunidades del universo">
        <div className="space-y-1 text-xs">
          {r.opportunities.slice(0, 12).map((o) => (
            <div key={o.ticker} className="flex items-baseline justify-between gap-2">
              <span>{o.ticker} <span className="text-term-muted">{o.name}</span> · <span className="text-term-info">{classLabel[o.class]}</span>{o.buyable ? " · comprable" : ""}</span>
              <span className="text-term-muted">{o.margin != null ? `${pct(o.margin)} (${o.source})` : "s/valoración"}</span>
            </div>
          ))}
        </div>
      </Panel>

      {/* 5. Riesgos */}
      <Panel title="5 · Riesgos y advertencias">
        <ul className="text-xs text-term-muted list-disc pl-4 space-y-1">{r.risks.map((x, i) => <li key={i}>{x}</li>)}</ul>
      </Panel>

      {/* Candidatas de investigación (NO comprables) */}
      {r.researchCandidates.length ? (
        <Panel title={`Candidatas de investigación (${r.researchCandidates.length}) · no comprables hasta análisis profundo`}>
          <div className="text-xs text-term-muted space-y-1">{r.researchCandidates.map((x) => <div key={x.ticker}>{x.ticker} {x.name ? `(${x.name})` : ""}: {x.reason}</div>)}</div>
        </Panel>
      ) : null}

      <Panel title="Metodología y control">
        <ul className="text-xs text-term-muted list-disc pl-4 space-y-1">
          {r.guardrails.map((g, i) => <li key={i}>{g}</li>)}
          <li>Cobertura: {r.coverage.evaluated}/{r.coverage.total} evaluados; con FV productivo {r.coverage.withProductiveFv}, con FCFF {r.coverage.withFcff}; bloqueados por DCF productivo {r.coverage.blockedByProductiveVeto.count} (pendientes, no descartados).</li>
        </ul>
      </Panel>
    </div>
  );
}
