"""DIAGNÓSTICO de credibilidad del motor de valoración (solo lectura, NO escribe, NO modifica motores).

Reconstruye el FCFF/DCF del driver data-driven (P2.4) de principio a fin para una lista de tickers,
exponiendo TODA la aritmética (datos de origen, fechas, revenue, EBIT, NOPAT, reinversión, FCFF por año,
WACC, g terminal, deuda neta, acciones, PV explícito vs terminal, valor por acción) y corre escenarios
contrafactuales para ATRIBUIR la discrepancia a supuestos concretos. No inventa nada: usa la misma serie
EODHD y el mismo driver que producen las valoraciones vigentes.

Uso: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY + EODHD_API_KEY en env.
     DIAG_TICKERS="PFE,AMGN,EOG,LOW,HD,UPS,NVDA,TSM" python -m app.jobs.valuation_diagnostic
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Dict, List, Optional

from app.research import fundamental_driver as D
from app.research.fcff_forward import (Assump, Base, value_path, p16_path,
                                       corrected_reinv_fn, wacc_of, RF, FX)

DEFAULT_TICKERS = ["PFE", "AMGN", "EOG", "LOW", "HD", "UPS", "NVDA", "TSM", "ASML", "MRK"]


def _fv_with(base: Base, a: Assump, g1: float, gT: float, margin_terminal: float, reinv_fn) -> dict:
    g, m = p16_path(g1, gT, base.ebit_margin0, margin_terminal, a.years)
    aa = Assump(**{**a.__dict__, "g1": g1, "margin_terminal": margin_terminal})
    return value_path(base, aa, g, m, gT=gT, reinv_fn=reinv_fn)


def diagnose(ticker: str, ccy: str, px: Optional[float], series: Dict, adr: int = 1) -> dict:
    """Replica EXACTAMENTE build() y además expone la proyección año a año y escenarios contrafactuales."""
    out: Dict = {"ticker": ticker, "ccy": ccy, "px": px, "adr": adr}
    # --- insumos de origen (idénticos a build) ---
    revenue = D._latest(series, "revenue"); ebit = D._latest(series, "operating_income")
    shares = D._latest(series, "shares"); total_debt = D._latest(series, "total_debt")
    cash = D._latest(series, "cash"); tax = D._latest(series, "tax"); net_income = D._latest(series, "net_income")
    rev_series = D._periods(series, "revenue"); capex = D._periods(series, "capex")
    dna = D._periods(series, "dna"); wc = D._periods(series, "wc_change")
    out["origen"] = {
        "revenue_latest": revenue, "revenue_series": rev_series,
        "operating_income_latest": ebit, "shares_latest": shares,
        "total_debt_latest": total_debt, "cash_latest": cash, "tax_latest": tax, "net_income_latest": net_income,
        "capex_series": capex, "dna_series": dna, "wc_change_series": wc,
        "fecha_fiscal_ultimo_revenue": rev_series[-1][0] if rev_series else None,
    }
    if not (revenue and revenue > 0 and shares and shares > 0 and ebit is not None and px and px > 0):
        out["status"] = "insuficiente (insumos)"; return out

    ebit_margin0 = ebit / revenue
    net_debt = (total_debt or 0.0) - (cash or 0.0)
    pretax = net_income / (1 - 0.21) if net_income else None
    eff_tax = D._clamp((tax / pretax) if (tax and pretax and pretax > 0) else 0.15, D.TAX_MIN, D.TAX_MAX)
    rev_cagr = D._cagr(series, "revenue"); n_years = len(rev_series)
    g1 = D._clamp(rev_cagr if rev_cagr is not None else 0.05, D.G1_MIN, D.G1_MAX)
    margin_terminal = D._clamp(min(ebit_margin0, 0.30), D.MARGIN_MIN, 0.30)
    mktcap = px * shares * FX.get(ccy, 1.0) * (adr or 1)
    dv = D._clamp((net_debt / (net_debt + mktcap)) if (net_debt > 0 and mktcap > 0) else 0.0, 0.0, D.DV_MAX)
    b = D.BETA_DEFAULT
    kd = RF[ccy] + 0.02
    rr = D._reinv_rates(series, revenue)
    s2c = D._clamp(1.0 / (rr[0] - rr[1]), D.S2C_MIN, D.S2C_MAX) if (rr and (rr[0] - rr[1]) > 0) else 2.0
    assump = Assump(beta=b, kd=kd, dv=dv, tax_norm=eff_tax, s2c=s2c, g1=g1,
                    margin_terminal=margin_terminal, roic_terminal=D.ROIC_TERMINAL_DEFAULT, years=10)
    base = Base(ticker=ticker, ccy=ccy, revenue=revenue, ebit_margin0=ebit_margin0,
                net_debt=net_debt, shares=shares, tax_rate=eff_tax, interest=0.0, adr=adr)
    reinv_fn = corrected_reinv_fn(*rr) if rr else None

    out["supuestos"] = {
        "ebit_margin0": round(ebit_margin0, 4), "rev_cagr_raw": rev_cagr, "g1_clamped": g1, "n_years": n_years,
        "eff_tax": round(eff_tax, 3), "net_debt": net_debt, "shares": shares, "dv": round(dv, 3),
        "beta": b, "kd": kd, "s2c": s2c, "margin_terminal": margin_terminal,
        "roic_terminal": D.ROIC_TERMINAL_DEFAULT, "gT": RF[ccy],
        "reinv_rates(capex%,dna%,wc%)": [round(x, 4) for x in rr] if rr else None,
        "reinv_neta_pct_rev(capex-dna)": round(rr[0] - rr[1], 4) if rr else None,
    }

    # --- valoración vigente (idéntica al driver) ---
    val = value_path(base, assump, *p16_path(g1, RF[ccy], ebit_margin0, margin_terminal, assump.years),
                     gT=RF[ccy], reinv_fn=reinv_fn)
    proj = val["proj"]
    fv = val["bridge"]["ps_usd"]
    out["valoracion_vigente"] = {
        "wacc": round(val["wacc"]["wacc"], 4), "wacc_menos_gT": round(val["wacc"]["wacc"] - RF[ccy], 4),
        "pv_fcff_explicito": round(proj["pv_fcff"], 1), "pv_valor_terminal": round(proj["pv_tv"], 1),
        "peso_terminal": round(proj["terminal_weight"], 3), "ev": round(proj["ev"], 1),
        "net_debt": round(base.net_debt, 1), "equity": round(val["bridge"]["equity"], 1),
        "fair_value_usd": round(fv, 2), "precio": px, "margen_vs_precio_pct": round((fv / px - 1) * 100, 1),
        "reinversion_terminal": round(proj["reinvest_terminal"], 3),
        "fcff_mayor_que_nopat_en_explicito": sum(1 for r in proj["rows"] if r["fcff"] > r["nopat"]),
        "anios_reinversion_negativa": sum(1 for r in proj["rows"] if r["reinvest"] < 0),
    }
    out["proyeccion_anual"] = [{
        "i": r["i"], "g": round(r["g"], 4), "rev": round(r["rev"], 1), "nopat": round(r["nopat"], 1),
        "reinvest": round(r["reinvest"], 1), "fcff": round(r["fcff"], 1),
    } for r in proj["rows"]]

    # --- escenarios contrafactuales: aíslan la contribución de cada supuesto al FV ---
    def fv_of(d):
        return round(d["bridge"]["ps_usd"], 2)
    esc = {}
    esc["A_base_driver"] = fv_of(val)
    # B: reinversión por s2c (positiva al crecer) en vez de (capex-D&A) corregida → aísla el efecto D&A
    esc["B_reinv_por_s2c_sin_capex_menos_dna"] = fv_of(_fv_with(base, assump, g1, RF[ccy], margin_terminal, None))
    # C: g terminal 2.5% en vez de RF
    esc["C_gT_2.5pct"] = fv_of(_fv_with(base, assump, g1, 0.025, margin_terminal, reinv_fn))
    # D: margen terminal 15% (compresión por patent cliff) en vez del margen actual
    esc["D_margenT_15pct"] = fv_of(_fv_with(base, assump, g1, RF[ccy], 0.15, reinv_fn))
    # E: crecimiento explícito 0% (patent cliff: sin crecimiento)
    esc["E_g1_0pct"] = fv_of(_fv_with(base, assump, 0.0, RF[ccy], margin_terminal, reinv_fn))
    # F: combinado defendible (reinv s2c + gT 2.5% + margenT 15% + g1 0%)
    esc["F_combinado_defendible"] = fv_of(_fv_with(base, assump, 0.0, 0.025, 0.15, None))
    out["escenarios_fv_usd"] = esc
    out["atribucion_vs_base"] = {k: round(v - esc["A_base_driver"], 2) for k, v in esc.items() if k != "A_base_driver"}
    return out


def run() -> dict:
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not srk or not os.getenv("EODHD_API_KEY"):
        return {"error": "faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / EODHD_API_KEY"}
    from app.jobs.supabase_writer import SupabaseWriter
    from app.core.connectors.eodhd import EodhdFundamentalsConnector, eodhd_annual_series_full
    w = SupabaseWriter(url, srk)
    conn = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
    tickers = [t.strip().upper() for t in (os.getenv("DIAG_TICKERS") or ",".join(DEFAULT_TICKERS)).split(",") if t.strip()]

    inlist = "in.(" + ",".join(tickers) + ")"
    prices = {str(r["ticker"]).upper(): r for r in
              w.select_rows("prices", select="ticker,close,currency", params={"ticker": inlist, "order": "ticker"})}
    instruments = {str(r["ticker"]).upper(): r for r in
                   w.select_rows("instruments", select="ticker,adr_ratio,sector", params={"ticker": inlist, "order": "ticker"})}

    results = []
    for t in tickers:
        pr = prices.get(t) or {}
        px = pr.get("close"); ccy = (pr.get("currency") or "").upper()
        try:
            adr = int((instruments.get(t, {}).get("adr_ratio")) or 1) or 1
        except (TypeError, ValueError):
            adr = 1
        try:
            _s, _ad, obj = conn._resolve(t)
            full = eodhd_annual_series_full(obj) if obj else {"currency": None, "by_field": {}}
            series = full.get("by_field", {})
            ccy = ccy or (full.get("currency") or "").upper()
        except Exception as e:
            results.append({"ticker": t, "error_fuente": f"{type(e).__name__}: {e}"}); continue
        try:
            d = diagnose(t, ccy or "", px, series, adr=adr)
            d["sector"] = instruments.get(t, {}).get("sector")
            results.append(d)
        except Exception as e:
            results.append({"ticker": t, "error_diag": f"{type(e).__name__}: {e}"})

    # resumen comparativo (señal sistémica)
    tabla = []
    for d in results:
        v = d.get("valoracion_vigente")
        if not v:
            tabla.append({"ticker": d["ticker"], "nota": d.get("status") or d.get("error_fuente") or d.get("error_diag")}); continue
        tabla.append({
            "ticker": d["ticker"], "sector": d.get("sector"), "fv": v["fair_value_usd"], "px": v["precio"],
            "margen_%": v["margen_vs_precio_pct"], "peso_terminal": v["peso_terminal"],
            "g1_%": round(d["supuestos"]["g1_clamped"] * 100, 1),
            "reinv_neta_%rev": d["supuestos"]["reinv_neta_pct_rev(capex-dna)"],
            "anios_reinv_neg": v["anios_reinversion_negativa"], "wacc_%": round(v["wacc"] * 100, 1),
        })
    return {"as_of": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()), "tabla_sistemica": tabla, "detalle": results}


def main(argv=None) -> int:
    out = run()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if "error" not in out else 1


if __name__ == "__main__":
    sys.exit(main())
