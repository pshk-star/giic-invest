"""P1.7.3 — DIAGNÓSTICO PRECISO de los campos prospectivos de EODHD (read-only, no escribe).

Para cada una de las 5 vuelca los campos CRUDOS tal como llegan y los contrasta con el ingreso/EPS
reportado, para determinar por qué el consenso salía inconsistente en P1.7.2 (escala, período
fiscal, moneda, ticker/ADR, split, campo mal interpretado o error del proveedor). No corrige nada:
expone la estructura real para decidir qué es utilizable.

Vuelca:
  - General: ticker resuelto, CurrencyCode, UpdatedAt, fin de año fiscal.
  - Earnings.Trend: TODOS los períodos (date, period, revenueEstimateAvg/Low/High/NumberOfAnalysts/
    Growth, earningsEstimateAvg/NumberOfAnalysts/Growth) + ratio del nivel vs reportado.
  - Earnings.History: últimos 4 (reportDate, epsEstimate, epsActual, beforeAfterMarket).
  - Highlights: EPSEstimate*, forward PE, revenue estimates si existen.
  - Reportado (fcff_base): revenue, EPS implícito (NI/acciones), moneda — referencia de contraste.

Uso: python -m app.research.eodhd_consensus_diag
"""
from __future__ import annotations

import json
import os
import sys

# Reportado (de fcff_base_full / P1.6) para contraste.
REPORTED = {
    "NVDA": {"ccy": "USD", "revenue": 215938e6, "ni": 120067e6, "shares": 24514e6, "fy_end": "ene"},
    "META": {"ccy": "USD", "revenue": 200966e6, "ni": 60458e6, "shares": 2574e6, "fy_end": "dic"},
    "NFLX": {"ccy": "USD", "revenue": 45183.036e6, "ni": 10981.201e6, "shares": 4344e6, "fy_end": "dic"},
    "TSM": {"ccy": "TWD", "revenue": 3809054e6, "ni": 1717883e6, "shares": 25927.6e6, "fy_end": "dic"},
    "ASML": {"ccy": "EUR", "revenue": 32667.3e6, "ni": 9609.4e6, "shares": 388.9e6, "fy_end": "dic"},
}
TICKERS = ["NVDA", "META", "NFLX", "TSM", "ASML"]


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def diag(t: str, obj: dict) -> dict:
    obj = obj or {}
    gen = obj.get("General", {}) or {}
    rep = REPORTED[t]
    rev0, ni0, sh0 = rep["revenue"], rep["ni"], rep["shares"]
    eps0 = ni0 / sh0 if sh0 else None
    trend = (obj.get("Earnings", {}) or {}).get("Trend", {}) or {}
    hist = (obj.get("Earnings", {}) or {}).get("History", {}) or {}
    hi = obj.get("Highlights", {}) or {}

    trend_rows = []
    for k in sorted(trend.keys()):
        d = trend[k] or {}
        rev = _num(d.get("revenueEstimateAvg"))
        eps = _num(d.get("earningsEstimateAvg"))
        trend_rows.append({
            "key": k, "date": d.get("date"), "period": d.get("period"),
            "revEstAvg": rev, "rev_vs_reported": round(rev / rev0, 4) if rev else None,
            "revGrowth": _num(d.get("revenueEstimateGrowth")),
            "revAnalysts": _num(d.get("revenueEstimateNumberOfAnalysts")),
            "epsEstAvg": eps, "eps_vs_reported": round(eps / eps0, 4) if (eps and eps0) else None,
            "epsGrowth": _num(d.get("earningsEstimateGrowth")),
            "epsAnalysts": _num(d.get("earningsEstimateNumberOfAnalysts")),
        })
    hist_rows = [{"period": p, **{k: (hist[p] or {}).get(k) for k in
                 ("reportDate", "beforeAfterMarket", "epsEstimate", "epsActual", "surprisePercent")}}
                 for p in sorted(hist.keys())[-4:]]
    return {
        "resolved_symbol": gen.get("Code"), "exchange": gen.get("Exchange"),
        "CurrencyCode": gen.get("CurrencyCode"), "UpdatedAt": gen.get("UpdatedAt"),
        "FiscalYearEnd": gen.get("FiscalYearEnd"),
        "reported": {"ccy": rep["ccy"], "revenue": rev0, "eps_implied": round(eps0, 4) if eps0 else None,
                     "fy_end": rep["fy_end"]},
        "highlights_forward": {k: _num(hi.get(k)) for k in
                               ("EPSEstimateCurrentYear", "EPSEstimateNextYear", "EPSEstimateCurrentQuarter",
                                "EPSEstimateNextQuarter", "ForwardPE")},
        "trend_periods": trend_rows,
        "history_recent": hist_rows,
        "n_trend": len(trend_rows),
    }


def main():
    key = os.getenv("EODHD_API_KEY", "")
    if not key:
        print(json.dumps({"error": "sin EODHD_API_KEY"}))
        return 0
    from app.core.connectors.eodhd import EodhdFundamentalsConnector
    conn = EodhdFundamentalsConnector(api_key=key)
    out = {}
    for t in TICKERS:
        try:
            sym, adr, obj = conn._resolve(t)
            out[t] = {"query_symbol": sym, "adr_ratio": adr, **diag(t, obj)} if obj else {"error": "sin objeto"}
        except Exception as e:
            out[t] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
