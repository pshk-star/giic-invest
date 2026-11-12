"""Auditoría de datos NVDA (item 1): de dónde sale el FCF, FY vs TTM, EODHD vs EDGAR, fechas y períodos.

Read-only. Responde con datos verificables:
 - Origen exacto del FCF FY2026 (endpoint, campos, filing_date, período fiscal, fuente).
 - OCF/CAPEX/FCF para FY2026 y para el TTM más reciente (reconstruido).
 - FCF TTM de EODHD (trimestres) y reconstruido con EDGAR (FY + YTD − YTD comparable).
 - Por qué GIIC usa 96,7B (FY) y no ~127B (TTM).
 - Chequeo de mezcla de períodos.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from typing import Dict, List, Optional


def _d(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _dur(a, b):
    da, db = _d(a), _d(b)
    return (db - da).days if (da and db) else None


def _classify(days):
    if days is None:
        return "instante"
    if 330 <= days <= 400:
        return "FY"
    if 250 <= days <= 290:
        return "YTD-9m"
    if 160 <= days <= 200:
        return "YTD-6m"
    if 80 <= days <= 100:
        return "Q"
    return f"{days}d"


def edgar_periods(rows, concept_names):
    """Lista de períodos de EDGAR para un concepto (con duración, clase, filing_date, valor, PIT)."""
    out = []
    for r in rows:
        if r.get("concept") not in concept_names:
            continue
        ps, pe = r.get("period_start"), r.get("period_end")
        days = _dur(ps, pe)
        out.append({"start": ps, "end": pe, "dias": days, "clase": _classify(days),
                    "valor": r.get("value"), "filing_date": r.get("filing_date"),
                    "concept": r.get("concept"), "unit": r.get("unit")})
    # PIT: por (start,end) el filing más reciente
    best = {}
    for o in out:
        k = (o["start"], o["end"])
        if k not in best or (o["filing_date"] or "") > (best[k]["filing_date"] or ""):
            best[k] = o
    return sorted(best.values(), key=lambda x: (x["end"] or "", x["clase"]))


def pick(periods, clase, end_year=None):
    cand = [p for p in periods if p["clase"] == clase]
    if end_year:
        cand = [p for p in cand if (p["end"] or "").startswith(str(end_year))]
    return cand[-1] if cand else None


def ttm_from_edgar(periods):
    """TTM = último FY + último YTD − YTD comparable del año anterior. Devuelve (valor, detalle)."""
    fy = pick(periods, "FY")
    ytds = [p for p in periods if p["clase"] in ("YTD-9m", "YTD-6m")]
    if not fy or not ytds:
        return None, {"motivo": "faltan FY o YTD", "fy": fy}
    cur = ytds[-1]
    clase = cur["clase"]
    cur_end = _d(cur["end"])
    prior = None
    for p in ytds:
        if p["clase"] == clase and p is not cur:
            pe = _d(p["end"])
            if pe and cur_end and 320 <= (cur_end - pe).days <= 400:
                prior = p
    if not prior:
        return None, {"motivo": f"falta YTD comparable anterior para {clase}", "cur": cur}
    val = fy["valor"] + cur["valor"] - prior["valor"]
    return val, {"formula": "FY + YTD_actual − YTD_anterior", "clase_ytd": clase,
                 "FY": {"end": fy["end"], "val": fy["valor"], "filed": fy["filing_date"]},
                 "YTD_actual": {"end": cur["end"], "val": cur["valor"], "filed": cur["filing_date"]},
                 "YTD_anterior": {"end": prior["end"], "val": prior["valor"], "filed": prior["filing_date"]}}


def run():
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    rows = w.select_rows("fundamentals_pit", select="concept,period_start,period_end,value,filing_date,unit,fiscal_period",
                         params={"ticker": "eq.NVDA", "order": "period_end"})
    OCF = ["NetCashProvidedByUsedInOperatingActivities"]
    CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment"]
    REV = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"]
    ocf_p = edgar_periods(rows, OCF); capex_p = edgar_periods(rows, CAPEX); rev_p = edgar_periods(rows, REV)

    # FY2026 (cierre enero 2026)
    fy_ocf = pick(ocf_p, "FY", 2026) or pick(ocf_p, "FY")
    fy_capex = pick(capex_p, "FY", 2026) or pick(capex_p, "FY")
    fy_fcf = (fy_ocf["valor"] - abs(fy_capex["valor"])) if (fy_ocf and fy_capex) else None

    # TTM EDGAR
    ttm_ocf, d_ocf = ttm_from_edgar(ocf_p)
    ttm_capex, d_capex = ttm_from_edgar(capex_p)
    ttm_rev, d_rev = ttm_from_edgar(rev_p)
    ttm_fcf = (ttm_ocf - abs(ttm_capex)) if (ttm_ocf is not None and ttm_capex is not None) else None

    # EODHD trimestral
    eod = {"disponible": False}
    if os.getenv("EODHD_API_KEY"):
        try:
            from app.core.connectors.eodhd import EodhdFundamentalsConnector
            c = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
            _s, _a, obj = c._resolve("NVDA")
            fin = (obj or {}).get("Financials", {})
            cfq = (fin.get("Cash_Flow", {}) or {}).get("quarterly", {}) or {}
            def num(d, keys):
                for k in keys:
                    v = (d or {}).get(k)
                    if v not in (None, "", "None"):
                        try: return float(v)
                        except: pass
                return None
            qs = sorted(cfq.items(), key=lambda kv: kv[0], reverse=True)[:4]
            q_ocf = [num(v, ["totalCashFromOperatingActivities"]) for _, v in qs]
            q_capex = [num(v, ["capitalExpenditures"]) for _, v in qs]
            hl = (obj or {}).get("Highlights", {}) or {}
            eod = {"disponible": True, "ultimos_4_trimestres": [k for k, _ in qs],
                   "ocf_trimestral": q_ocf, "capex_trimestral": q_capex,
                   "ttm_ocf": sum(x for x in q_ocf if x is not None) if all(x is not None for x in q_ocf) else None,
                   "ttm_capex": sum(x for x in q_capex if x is not None) if all(x is not None for x in q_capex) else None,
                   "highlights_mostRecentQuarter": hl.get("MostRecentQuarter")}
            if eod["ttm_ocf"] is not None and eod["ttm_capex"] is not None:
                eod["ttm_fcf"] = eod["ttm_ocf"] - abs(eod["ttm_capex"])
        except Exception as e:
            eod = {"disponible": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}

    return {
        "FY2026": {"ocf": fy_ocf, "capex": fy_capex, "fcf": fy_fcf,
                   "origen": "EDGAR companyfacts; concepto NetCashProvidedByUsedInOperatingActivities − "
                             "PaymentsToAcquirePropertyPlantAndEquipment; período FY (≈364 días)"},
        "TTM_EDGAR": {"ocf": ttm_ocf, "capex": ttm_capex, "fcf": ttm_fcf,
                      "detalle_ocf": d_ocf, "detalle_capex": d_capex, "rev": ttm_rev, "detalle_rev": d_rev},
        "TTM_EODHD": eod,
        "periodos_OCF_EDGAR": ocf_p[-10:],
        "explicacion": "El motor usa el FCF del último FY (FY2026, cierre enero 2026) = OCF−capex. El TTM "
                       "más reciente (FY + YTD actual − YTD anterior) es mayor porque NVDA siguió creciendo "
                       "tras el cierre anual. GIIC debe usar TTM, no el FY rezagado.",
    }


def main(argv=None):
    print(json.dumps(run(), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
