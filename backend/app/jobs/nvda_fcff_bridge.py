"""Puente FCFF NVDA (item 1-4): transición FCF TTM $127B -> FCFF proyectado año 1, descompuesta.

Muestra NOPAT, D&A, CAPEX, ΔWC y reinversión; compara ROIC MEDIO vs ROIC INCREMENTAL; prueba si la
fórmula g/ROIC con ROIC medio exige capital que la estructura de NVDA no requiere. Read-only, sin ajustes.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional

from app.research.edgar_series import build_series_from_rows, fetch_edgar_rows
from app.research.valuation_engine import reconcile, normalize, RF, ERP, YEARS, _clamp, ROIC_CAP


def _eodhd(t):
    if not os.getenv("EODHD_API_KEY"):
        return {"currency": None, "by_field": {}}, {}
    from app.core.connectors.eodhd import EodhdFundamentalsConnector, eodhd_annual_series_full
    c = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
    _s, _a, obj = c._resolve(t)
    return (eodhd_annual_series_full(obj) if obj else {"currency": None, "by_field": {}}), (obj or {})


def run(ticker="NVDA"):
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    px = None
    for r in w.select_rows("prices", select="ticker,close", params={"ticker": f"eq.{ticker}", "order": "ticker"}):
        px = r.get("close")
    erows = fetch_edgar_rows(w, ticker)
    edgar = build_series_from_rows(erows)
    eod, eod_obj = _eodhd(ticker)
    rec = reconcile(edgar, eod)
    n = normalize(ticker, rec, px)
    by = rec.by_field

    # TTM oficial (suma 4 trimestres) para NOPAT/FCF base
    official = {}
    try:
        from app.providers.edgar import EDGARProvider
        from app.research.ttm import ttm_by_quarters
        prov = EDGARProvider(user_agent=os.getenv("EDGAR_USER_AGENT") or "GIIC research noreply@giic.example")
        prov._load_ciks()
        facts = prov._facts(ticker)
        usg = (facts.get("facts", {}) or {}).get("us-gaap", {}) or {}
        official = ttm_by_quarters(usg, eod_obj, {"10-K", "10-K/A", "10-Q", "10-Q/A"}).get("ttm", {})
    except Exception as e:
        official = {"_err": str(e)}

    def tt(f):
        b = official.get(f); return b.get("ttm") if isinstance(b, dict) else None
    rev_ttm = tt("revenue"); ebit_ttm = tt("operating_income"); ocf_ttm = tt("ocf"); capex_ttm = tt("capex")
    fcf_ttm = (ocf_ttm - abs(capex_ttm)) if (ocf_ttm and capex_ttm) else None

    # serie anual: NOPAT_t e invested_capital_t para ROIC medio vs incremental
    tax_eff = n.tax_eff if n.ok else 0.15
    annual = []
    for p in sorted(by.get("revenue", {})):
        ebit = by.get("operating_income", {}).get(p); ic = by.get("invested_capital", {}).get(p)
        dna = by.get("dna", {}).get(p); capex = by.get("capex", {}).get(p); wc = by.get("wc_change", {}).get(p)
        if ebit is not None:
            annual.append({"p": p, "nopat": ebit * (1 - tax_eff), "ic": ic, "dna": dna,
                           "capex": capex, "wc": wc, "ebit": ebit})

    nopat0 = (ebit_ttm * (1 - tax_eff)) if ebit_ttm else (n.nopat0 if n.ok else None)
    ic0 = n.invested_capital if n.ok else None
    roic_avg = (nopat0 / ic0) if (nopat0 and ic0) else None

    # ROIC INCREMENTAL: ΔNOPAT / ΔInvested_capital en ventana reciente (~3-4 años)
    roic_incr = None; incr_detail = {}
    pts = [a for a in annual if a["nopat"] is not None and a["ic"] is not None][-5:]
    if len(pts) >= 2:
        dn = pts[-1]["nopat"] - pts[0]["nopat"]; di = pts[-1]["ic"] - pts[0]["ic"]
        roic_incr = (dn / di) if di and di > 0 else None
        incr_detail = {"desde": pts[0]["p"], "hasta": pts[-1]["p"], "d_nopat": dn, "d_ic": di}

    # D&A, capex, ΔWC TTM (de EODHD si existe; si no, del último anual)
    def eod_ttm_q(field):
        from app.research.ttm import eod_quarters
        q = eod_quarters(eod_obj, field) if field in ("ocf", "capex") else {}
        vals = [v for _, v in sorted(q.items(), reverse=True)[:4]]
        return sum(vals) if len(vals) == 4 else None
    last = annual[-1] if annual else {}
    dna_ttm = None  # D&A no está en quarterly de EODHD de forma fiable; se usa proporción anual
    if last.get("dna") is not None and last.get("ebit") and ebit_ttm:
        dna_ttm = last["dna"] * (ebit_ttm / last["ebit"])     # escala D&A al EBIT TTM (aprox trazable)
    wc_ttm = None
    if last.get("wc") is not None and last.get("ebit") and ebit_ttm:
        wc_ttm = last["wc"] * (ebit_ttm / last["ebit"])

    # DESCOMPOSICIÓN del reinversión actual: net_reinv = (capex − D&A) + ΔWC ; FCFF = NOPAT − net_reinv
    net_reinv_actual = None
    if capex_ttm is not None and dna_ttm is not None:
        net_reinv_actual = (abs(capex_ttm) - abs(dna_ttm)) + (wc_ttm or 0)
    fcff_actual = (nopat0 - net_reinv_actual) if (nopat0 and net_reinv_actual is not None) else None

    g1 = n.g1 if n.ok else 0.25
    # Reinversión PROYECTADA año 1 bajo tres tratamientos
    def reinv(roic): return (g1 / roic * nopat0) if (roic and roic > 0 and nopat0) else None
    reinv_avg = reinv(_clamp(roic_avg, 0.06, ROIC_CAP)) if roic_avg else None       # actual (ROIC medio capado)
    reinv_incr = reinv(roic_incr) if roic_incr else None                            # ROIC incremental
    fcff_avg = (nopat0 - reinv_avg) if (nopat0 and reinv_avg is not None) else None
    fcff_incr = (nopat0 - reinv_incr) if (nopat0 and reinv_incr is not None) else None

    return {
        "ticker": ticker, "tax_eff": tax_eff,
        "TTM": {"revenue": rev_ttm, "ebit": ebit_ttm, "nopat0": nopat0, "ocf": ocf_ttm, "capex": capex_ttm,
                "dna_aprox": dna_ttm, "wc_aprox": wc_ttm, "fcf_real": fcf_ttm},
        "capital": {"invested_capital": ic0, "roic_medio": roic_avg, "roic_incremental": roic_incr,
                    "incr_detalle": incr_detail},
        "reinversion_actual": {"net_reinv=(capex−D&A)+ΔWC": net_reinv_actual, "fcff_implicito": fcff_actual,
                               "vs_fcf_real": fcf_ttm},
        "proyeccion_ano1": {
            "g1": g1,
            "ROIC_medio": {"roic": _clamp(roic_avg, 0.06, ROIC_CAP) if roic_avg else None,
                           "reinversion": reinv_avg, "fcff": fcff_avg,
                           "dif_vs_fcf_real_pct": (round((fcff_avg / fcf_ttm - 1) * 100, 1) if (fcff_avg and fcf_ttm) else None)},
            "ROIC_incremental": {"roic": roic_incr, "reinversion": reinv_incr, "fcff": fcff_incr,
                                 "dif_vs_fcf_real_pct": (round((fcff_incr / fcf_ttm - 1) * 100, 1) if (fcff_incr and fcf_ttm) else None)},
        },
        "diagnostico": "La fórmula g/ROIC con ROIC MEDIO exige reinversión = g/ROIC_medio·NOPAT. Si el ROIC "
                       "incremental (ΔNOPAT/ΔIC) es mayor que el medio, el medio SOBREESTIMA la reinversión "
                       "(capital que NVDA no requiere). No hay doble conteo; hay ROIC equivocado.",
        "serie_anual": [{k: a.get(k) for k in ("p", "nopat", "ic", "dna", "capex", "wc")} for a in annual[-5:]],
    }


def main(argv=None):
    print(json.dumps(run((argv or sys.argv[1:] or ["NVDA"])[0]), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
