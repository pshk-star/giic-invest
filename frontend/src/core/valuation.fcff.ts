// ============================================================================
// valuation.fcff.ts — MOTOR FUNDAMENTAL FCFF EVALUABLE (NO PRODUCTIVO) — P1.6
// ----------------------------------------------------------------------------
// Valoración de empresas OPERATIVAS por FCFF (Damodaran / CFA Institute). NO está
// cableado a `fairValueDCF` ni a Advisor 2.2; se activa sólo tras aprobación.
// Lee la capa de datos `fcff_inputs` (P1.5.1-A) + supuestos de mercado documentados.
//
// Separación explícita: datos REPORTADOS (base) vs SUPUESTOS del modelo (assumptions).
// Moneda: los flujos se descuentan en SU moneda nominal; nunca un Ke USD sobre flujos TWD/EUR.
// ============================================================================

export type Ccy = "USD" | "EUR" | "TWD";

export interface MarketParams {
  rf: Record<Ccy, number>;      // libres de riesgo 10y por moneda (fechadas)
  erp: number;                   // prima de riesgo de acciones (mercado maduro)
  crp: Record<Ccy, number>;      // prima de riesgo país
  fxToUsd: Record<Ccy, number>;  // conversión a USD
}

export const MARKET_2026_11_10: MarketParams = {
  rf: { USD: 0.041, EUR: 0.026, TWD: 0.015 },
  erp: 0.045,
  crp: { USD: 0.0, EUR: 0.0, TWD: 0.0085 },
  fxToUsd: { USD: 1.0, EUR: 1.1203, TWD: 1 / 32.80 },
};

export interface CompanyBase {   // DATOS REPORTADOS (de fcff_inputs)
  ticker: string; ccy: Ccy; period: string;
  revenue: number; ebitMargin0: number; netDebt: number; shares: number;
  adr?: number;                  // ordinarias por ADR (TSM=5, resto 1)
  eligibility: "eligible" | "degraded" | "ineligible" | "na";
}

export interface Assumptions {   // SUPUESTOS DEL MODELO (documentados)
  beta: number; kd: number; dv: number; taxNorm: number; salesToCapital: number;
  g1: number; gTerminal?: number; marginTerminal: number; roicTerminal: number;
  years?: number;
}

export interface WaccResult {
  rf: number; beta: number; erp: number; crp: number; ke: number;
  kd: number; dv: number; taxNorm: number; wacc: number; explain: string;
}

export function computeWacc(a: Assumptions, ccy: Ccy, m: MarketParams, dWacc = 0): WaccResult {
  const rf = m.rf[ccy], crp = m.crp[ccy];
  const ke = rf + a.beta * (m.erp + crp);
  const wacc = (1 - a.dv) * ke + a.dv * a.kd * (1 - a.taxNorm) + dWacc;
  return {
    rf, beta: a.beta, erp: m.erp, crp, ke, kd: a.kd, dv: a.dv, taxNorm: a.taxNorm, wacc,
    explain: `Ke=${(ke * 100).toFixed(2)}% = ${(rf * 100).toFixed(1)}+${a.beta}·(${(m.erp * 100).toFixed(1)}+${(crp * 100).toFixed(2)}); `
      + `WACC=(1-${a.dv})·Ke+${a.dv}·${(a.kd * 100).toFixed(1)}·(1-${a.taxNorm})=${(wacc * 100).toFixed(2)}%`,
  };
}

export interface ProjYear { i: number; g: number; revenue: number; margin: number; nopat: number; reinvest: number; fcff: number; roic: number; }
export interface Projection { rows: ProjYear[]; pvFcff: number; pvTerminal: number; ev: number; terminalWeight: number; reinvestTerminal: number; }

/** Proyección explícita 10a. Reinversión = ΔRevenue / (ventas/capital). FCFF = NOPAT − Reinversión.
 *  Terminal CONSISTENTE: reinversión_T = gT/ROIC_T; TV = NOPAT_{T+1}(1−gT/ROIC_T)/(WACC−gT). */
export function projectFcff(base: CompanyBase, a: Assumptions, gT: number, marginT: number, wacc: number): Projection {
  const years = a.years ?? 10;
  if (!(wacc > gT)) throw new Error("WACC debe exceder gT");
  const rows: ProjYear[] = [];
  let pv = 0, revPrev = base.revenue;
  for (let i = 1; i <= years; i++) {
    const g = a.g1 + (gT - a.g1) * (i - 1) / (years - 1);
    const revenue = revPrev * (1 + g);
    const margin = base.ebitMargin0 + (marginT - base.ebitMargin0) * i / years;
    const nopat = revenue * margin * (1 - a.taxNorm);
    const reinvest = (revenue - revPrev) / a.salesToCapital;
    const fcff = nopat - reinvest;
    const roic = nopat / (revenue / a.salesToCapital);
    pv += fcff / Math.pow(1 + wacc, i);
    rows.push({ i, g, revenue, margin, nopat, reinvest, fcff, roic });
    revPrev = revenue;
  }
  const revT1 = revPrev * (1 + gT);
  const nopatT1 = revT1 * marginT * (1 - a.taxNorm);
  const rrT = gT / a.roicTerminal;
  const fcffT1 = nopatT1 * (1 - rrT);
  const tv = fcffT1 / (wacc - gT);
  const pvTv = tv / Math.pow(1 + wacc, years);
  const ev = pv + pvTv;
  return { rows, pvFcff: pv, pvTerminal: pvTv, ev, terminalWeight: pvTv / ev, reinvestTerminal: rrT };
}

export interface EquityBridge { ev: number; netDebt: number; equity: number; perShareLocal: number; perShareUsd: number; }

/** EV→Equity: equity = EV − deuda neta (neta de caja/no operativos; leases ya en deuda → no doble conteo).
 *  SBC ya está GASTADO en EBIT (no se vuelve a restar); la dilución se refleja en acciones diluidas. */
export function evToEquity(base: CompanyBase, ev: number, m: MarketParams): EquityBridge {
  const equity = ev - base.netDebt;              // netDebt<0 (caja neta) suma
  const perShareLocal = equity / base.shares;
  const perShareUsd = perShareLocal * m.fxToUsd[base.ccy] * (base.adr ?? 1);
  return { ev, netDebt: base.netDebt, equity, perShareLocal, perShareUsd };
}

export interface FcffScenario { name: string; wacc: WaccResult; projection: Projection; bridge: EquityBridge; gTerminal: number; }

export function valueScenario(base: CompanyBase, a: Assumptions, m: MarketParams,
                              d: { dg1?: number; dMargin?: number; dWacc?: number; dGt?: number } = {}): FcffScenario {
  const gT = (a.gTerminal ?? m.rf[base.ccy]) + (d.dGt ?? 0);   // terminal ≤ rf nominal de la moneda
  const wacc = computeWacc(a, base.ccy, m, d.dWacc ?? 0);
  const aa: Assumptions = { ...a, g1: a.g1 * (1 + (d.dg1 ?? 0)) };
  const projection = projectFcff(base, aa, gT, a.marginTerminal + (d.dMargin ?? 0), wacc.wacc);
  const bridge = evToEquity(base, projection.ev, m);
  return { name: "scenario", wacc, projection, bridge, gTerminal: gT };
}

/** Reverse DCF: g1 (vía multiplicador) que iguala el FV FCFF al precio actual. */
export function reverseG1(base: CompanyBase, a: Assumptions, m: MarketParams, price: number): number {
  let lo = -0.9, hi = 4.0;
  for (let k = 0; k < 60; k++) {
    const mid = (lo + hi) / 2;
    const ps = valueScenario(base, a, m, { dg1: mid }).bridge.perShareUsd;
    if (ps < price) lo = mid; else hi = mid;
  }
  return a.g1 * (1 + (lo + hi) / 2);
}

/** Rejilla de sensibilidad WACC × gT (FV/acción USD). */
export function sensitivity(base: CompanyBase, a: Assumptions, m: MarketParams,
                            dWaccs = [-0.01, 0, 0.01], dGts = [-0.005, 0, 0.005]): number[][] {
  return dWaccs.map((dw) => dGts.map((dg) => valueScenario(base, a, m, { dWacc: dw, dGt: dg }).bridge.perShareUsd));
}

export interface FcffValuation {
  ticker: string; available: boolean; reason?: string;
  base: CompanyBase; wacc: WaccResult; gTerminal: number;
  projection: Projection; bridge: EquityBridge;
  scenarios: { conservador: number; base: number; optimista: number };
  terminalWeight: number; reverseG1: number;
  confidence: "alta" | "media" | "baja";
  confidenceReason: string;
}

/** Punto de entrada evaluable. Devuelve no-disponible (no una cifra falsa) si los datos no son aptos. */
export function fairValueFcff(base: CompanyBase, a: Assumptions, m: MarketParams, price: number): FcffValuation {
  if (base.eligibility === "na")
    return { available: false, reason: "FCFF no aplica (financiera/vehículo)", ticker: base.ticker } as unknown as FcffValuation;
  if (base.eligibility === "ineligible")
    return { available: false, reason: "datos insuficientes/invalidos para FCFF", ticker: base.ticker } as unknown as FcffValuation;

  const baseS = valueScenario(base, a, m);
  const cons = valueScenario(base, a, m, { dg1: -0.25, dMargin: -0.03, dWacc: +0.01, dGt: -0.005 }).bridge.perShareUsd;
  const opt = valueScenario(base, a, m, { dg1: +0.20, dMargin: +0.03, dWacc: -0.01, dGt: +0.003 }).bridge.perShareUsd;
  const fv = baseS.bridge.perShareUsd;

  // Confianza: dispersión de escenarios + calidad de datos. Mayor dispersión o datos degradados ⇒ menor confianza.
  const spread = fv > 0 ? (opt - cons) / fv : 99;
  let confidence: "alta" | "media" | "baja";
  if (base.eligibility === "degraded" || spread > 2.0 || baseS.projection.terminalWeight > 0.75) confidence = "baja";
  else if (spread > 1.0 || baseS.projection.terminalWeight >= 0.6) confidence = "media";
  else confidence = "alta";

  return {
    ticker: base.ticker, available: true, base, wacc: baseS.wacc, gTerminal: baseS.gTerminal,
    projection: baseS.projection, bridge: baseS.bridge,
    scenarios: { conservador: cons, base: fv, optimista: opt },
    terminalWeight: baseS.projection.terminalWeight, reverseG1: reverseG1(base, a, m, price),
    confidence,
    confidenceReason: `dispersión cons→opt ${(spread * 100).toFixed(0)}% del FV; peso terminal ${(baseS.projection.terminalWeight * 100).toFixed(0)}%; elegibilidad ${base.eligibility}`,
  };
}

// --- Configuración de las cinco (SUPUESTOS documentados; base = datos reportados de fcff_inputs) ---
export const FCFF_ASSUMPTIONS: Record<string, Assumptions> = {
  NVDA: { beta: 1.35, kd: 0.048, dv: 0.02, taxNorm: 0.15, salesToCapital: 2.7, g1: 0.30, marginTerminal: 0.45, roicTerminal: 0.22 },
  META: { beta: 1.20, kd: 0.050, dv: 0.08, taxNorm: 0.14, salesToCapital: 1.3, g1: 0.15, marginTerminal: 0.38, roicTerminal: 0.20 },
  NFLX: { beta: 1.10, kd: 0.053, dv: 0.12, taxNorm: 0.14, salesToCapital: 2.0, g1: 0.12, marginTerminal: 0.30, roicTerminal: 0.18 },
  TSM:  { beta: 1.15, kd: 0.023, dv: 0.03, taxNorm: 0.16, salesToCapital: 0.8, g1: 0.18, marginTerminal: 0.42, roicTerminal: 0.18 },
  ASML: { beta: 1.25, kd: 0.030, dv: 0.05, taxNorm: 0.175, salesToCapital: 2.2, g1: 0.14, marginTerminal: 0.38, roicTerminal: 0.25 },
};
