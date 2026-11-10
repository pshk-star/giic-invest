"""P1.7 — SONDEO READ-ONLY de datos PROSPECTIVOS de EODHD (no escribe nada).

Verifica empíricamente, para las 5, qué campos forward trae el endpoint /fundamentals que YA
pagamos y consultamos, su cobertura, profundidad de historia y si hay POINT-IN-TIME. NO asume
disponibilidad: inspecciona el objeto crudo. Reutiliza el conector existente.

Uso: python -m app.research.eodhd_forward_probe
"""
from __future__ import annotations
import json, os, sys
from app.core.connectors.eodhd import EodhdFundamentalsConnector

TICKERS = ["NVDA", "META", "NFLX", "TSM", "ASML"]


def _keys(d, n=8):
    return sorted(list(d.keys()))[:n] if isinstance(d, dict) else type(d).__name__


def probe(obj: dict) -> dict:
    earn = (obj or {}).get("Earnings", {}) or {}
    hist = earn.get("History", {}) or {}
    trend = earn.get("Trend", {}) or {}
    ar = (obj or {}).get("AnalystRatings", {}) or {}
    hi = (obj or {}).get("Highlights", {}) or {}
    val = (obj or {}).get("Valuation", {}) or {}
    # Historia de sorpresas (epsActual vs epsEstimate) = PIT en la fecha de reporte.
    hperiods = sorted(hist.keys())
    hsample = hist.get(hperiods[-1], {}) if hperiods else {}
    # Trend = estimaciones forward (snapshot ACTUAL; sin historia PIT propia).
    tperiods = sorted(trend.keys())
    tsample = trend.get(tperiods[-1], {}) if tperiods else {}
    return {
        "Earnings.History": {"n": len(hperiods), "rango": [hperiods[0], hperiods[-1]] if hperiods else None,
                             "campos": _keys(hsample), "muestra": {k: hsample.get(k) for k in
                               ("epsActual", "epsEstimate", "epsDifference", "surprisePercent", "reportDate", "beforeAfterMarket") if k in hsample}},
        "Earnings.Trend": {"n": len(tperiods), "periodos": tperiods[-4:],
                           "campos": _keys(tsample, 20), "muestra": {k: tsample.get(k) for k in
                             ("date", "period", "growth", "earningsEstimateAvg", "earningsEstimateNumberOfAnalysts",
                              "revenueEstimateAvg", "epsTrendCurrent", "epsTrend7daysAgo", "epsTrend30daysAgo",
                              "epsRevisionsUpLast30days", "epsRevisionsDownLast30days") if k in tsample}},
        "AnalystRatings": {"presente": bool(ar), "campos": _keys(ar, 12),
                           "muestra": {k: ar.get(k) for k in ("Rating", "TargetPrice", "StrongBuy", "Buy", "Hold", "Sell", "StrongSell") if k in ar}},
        "Highlights.forward": {k: hi.get(k) for k in ("ForwardPE", "PEGRatio", "EPSEstimateCurrentYear",
                               "EPSEstimateNextYear", "EPSEstimateNextQuarter", "EPSEstimateCurrentQuarter") if k in hi},
        "Valuation": {k: val.get(k) for k in ("ForwardPE", "PriceSalesTTM", "EnterpriseValueEbitda") if k in val},
        "updated": (obj.get("General", {}) or {}).get("UpdatedAt"),
    }


def main():
    key = os.getenv("EODHD_API_KEY", "")
    if not key:
        print(json.dumps({"error": "sin EODHD_API_KEY"})); return 0
    conn = EodhdFundamentalsConnector(api_key=key)
    out = {}
    for t in TICKERS:
        try:
            sym, _adr, obj = conn._resolve(t)
            out[t] = {"symbol": sym, **probe(obj)} if obj else {"error": "sin objeto"}
        except Exception as e:
            out[t] = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
