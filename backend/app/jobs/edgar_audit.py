"""Auditoría de cobertura y CALIDAD de fundamentals_pit (no solo el total de registros).

Reporta: empresas con datos utilizables, profundidad histórica real, cobertura por
concepto, fechas de publicación y accession, reexpresiones, y detección de cifras
trimestrales vs acumuladas YTD (span del periodo). Es análisis de solo lectura.

Uso: python -m app.jobs.edgar_audit            (lee de Supabase, imprime informe)
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import date

FLOW_CONCEPTS = {  # conceptos de FLUJO (pueden venir trimestrales o YTD acumulados)
    "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
    "NetIncomeLoss", "GrossProfit", "OperatingIncomeLoss",
    "NetCashProvidedByUsedInOperatingActivities", "PaymentsToAcquirePropertyPlantAndEquipment",
}


def _days(a: str, b: str) -> int:
    from datetime import date as d
    ya, ma, da = map(int, a.split("-"))
    yb, mb, db = map(int, b.split("-"))
    return (d(yb, mb, db) - d(ya, ma, da)).days


def audit(rows: list) -> dict:
    by_ticker = defaultdict(set)              # ticker -> set(period_end)
    by_concept = defaultdict(lambda: {"rows": 0, "tickers": set()})
    restated = defaultdict(set)               # (ticker,concept,period_end,unit) -> set(accession)
    periods_per_ticker_concept = defaultdict(set)
    ytd_flags = {"quarterly": 0, "ytd_cumulative": 0, "annual": 0, "unknown": 0}
    missing_filing = 0
    accns = set()
    forms = defaultdict(int)

    for r in rows:
        t, c, pe = r.get("ticker"), r.get("concept"), r.get("period_end")
        unit = r.get("unit"); acc = r.get("accession"); ps = r.get("period_start")
        form = (r.get("form_type") or "")
        if r.get("filing_date") in (None, ""):
            missing_filing += 1
        if acc:
            accns.add(acc)
        forms[form] += 1
        by_ticker[t].add(pe)
        by_concept[c]["rows"] += 1
        by_concept[c]["tickers"].add(t)
        restated[(t, c, pe, unit)].add(acc)
        periods_per_ticker_concept[(t, c)].add(pe)
        # trimestral vs YTD por span (solo conceptos de flujo con period_start)
        if c in FLOW_CONCEPTS and ps and pe:
            try:
                span = _days(ps, pe)
            except Exception:
                span = None
            if span is None:
                ytd_flags["unknown"] += 1
            elif span <= 100:
                ytd_flags["quarterly"] += 1
            elif span <= 280:
                ytd_flags["ytd_cumulative"] += 1
            else:
                ytd_flags["annual"] += 1

    # empresas utilizables: >=4 periodos y >=5 conceptos
    usable = 0
    depth_years = []
    for t, pes in by_ticker.items():
        concepts_t = len({c for (tt, c) in periods_per_ticker_concept if tt == t})
        if len(pes) >= 4 and concepts_t >= 5:
            usable += 1
        valid = sorted(p for p in pes if p)
        if len(valid) >= 2:
            depth_years.append(round(_days(valid[0], valid[-1]) / 365.0, 1))
    depth_years.sort()
    median_depth = depth_years[len(depth_years) // 2] if depth_years else None

    # reexpresiones: claves con >1 accession
    restatements = sum(1 for k, accset in restated.items() if len([a for a in accset if a]) > 1)

    return {
        "total_rows": len(rows),
        "tickers_with_data": len(by_ticker),
        "usable_companies(>=4 periodos,>=5 conceptos)": usable,
        "historical_depth_years": {"median": median_depth,
                                   "min": depth_years[0] if depth_years else None,
                                   "max": depth_years[-1] if depth_years else None},
        "distinct_accessions": len(accns),
        "rows_missing_filing_date": missing_filing,
        "forms_top": dict(sorted(forms.items(), key=lambda x: -x[1])[:6]),
        "coverage_by_concept": {c: {"rows": v["rows"], "tickers": len(v["tickers"])}
                                for c, v in sorted(by_concept.items(), key=lambda x: -x[1]["rows"])},
        "restatements(claves con >1 filing)": restatements,
        "flow_period_type": ytd_flags,
        "ytd_note": "span<=100d=trimestral; 100-280d=YTD acumulado; >280d=anual. Para features de flujo se normalizará a trimestral (diferenciando YTD consecutivos).",
    }


def execute() -> dict:
    from .supabase_writer import SupabaseWriter
    w = SupabaseWriter(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    rows = w.select_rows("fundamentals_pit",
                         select="ticker,concept,period_end,period_start,filing_date,accession,unit,form_type")
    rep = audit(rows)
    rep["as_of"] = date.today().isoformat()
    return rep


def main(argv=None):
    try:
        print(json.dumps(execute(), indent=2, default=str))
    except Exception as e:
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:200]}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
