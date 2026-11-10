"""P2.0 — Reporte de riesgo de portafolio sobre datos REALES (price_history de Supabase).

Arma retornos alineados desde price_history y corre el motor puro `portfolio_risk` para producir
MÉTRICAS reproducibles (concentración, solape ETF, vol/correlación, drawdown, FX, estrés,
contribución al riesgo, impacto marginal, beta a benchmark). NO genera recomendaciones: es el
insumo que consumirá Advisor 3.0. Los pesos del portafolio son un INSUMO (archivo/represent.);
la reconstrucción desde transacciones con contexto de usuario es el punto de integración de Advisor 3.0.

Uso: python -m app.jobs.portfolio_risk_report [--no-net]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Dict, List

from app.research import portfolio_risk as pr

# Portafolio representativo (MVP) + metadatos. Reemplazable por la cartera real (Advisor 3.0).
WEIGHTS = {"NVDA": 0.25, "META": 0.20, "NFLX": 0.10, "TSM": 0.15, "ASML": 0.10, "SPY": 0.20}
META = {
    "NVDA": {"sector": "Technology", "country": "US", "currency": "USD"},
    "META": {"sector": "Communication Services", "country": "US", "currency": "USD"},
    "NFLX": {"sector": "Communication Services", "country": "US", "currency": "USD"},
    "TSM": {"sector": "Technology", "country": "TW", "currency": "USD"},
    "ASML": {"sector": "Technology", "country": "NL", "currency": "USD"},
    "SPY": {"sector": "ETF", "country": "US", "currency": "USD"},
}
BENCH = "SPY"
STRESS = {
    "selloff_tech_-30": {"by_sector": {"Technology": -0.30, "Communication Services": -0.20,
                                       "ETF": -0.15}, "default": -0.10},
    "subida_tasas": {"by_sector": {"Technology": -0.12, "Communication Services": -0.08,
                                   "ETF": -0.06}, "default": -0.05},
}


def _returns_from_prices(rows: List[dict]) -> Dict[str, List[float]]:
    by: Dict[str, List[tuple]] = {}
    for r in rows:
        by.setdefault(r["ticker"], []).append((r["as_of"], float(r["close"])))
    # alinear por fechas comunes
    series = {t: dict(v) for t, v in by.items()}
    common = None
    for t, d in series.items():
        s = set(d.keys())
        common = s if common is None else (common & s)
    dates = sorted(common or [])
    rets: Dict[str, List[float]] = {}
    for t, d in series.items():
        px = [d[dt] for dt in dates]
        rets[t] = [px[k] / px[k - 1] - 1.0 for k in range(1, len(px)) if px[k - 1] > 0]
    return rets, dates


def run(no_net: bool) -> dict:
    tickers = list(WEIGHTS.keys())
    out: dict = {"P2.0": "riesgo de portafolio (métricas; sin recomendaciones)",
                 "pesos": WEIGHTS, "benchmark": BENCH}
    # Concentración / FX / solape no requieren retornos
    out["concentracion"] = {k: pr.concentration(WEIGHTS, META, k) for k in ("sector", "country", "currency")}
    out["fx"] = pr.fx_exposure(WEIGHTS, META, "USD")
    # Solape económico: look-through de SPY (muestra) desde etf_snapshots si hay red
    lookthrough: Dict[str, Dict[str, float]] = {}
    rets: Dict[str, List[float]] = {}
    if not no_net and os.getenv("SUPABASE_URL"):
        try:
            from app.jobs.supabase_writer import SupabaseWriter
            w = SupabaseWriter(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
            rows = w.select_rows("price_history", select="ticker,as_of,close",
                                 params={"ticker": "in.(%s)" % ",".join(tickers),
                                         "order": "as_of.asc"})
            rets, dates = _returns_from_prices(rows)
            out["cobertura_precios"] = {t: len(rets.get(t, [])) for t in tickers}
            out["ventana"] = [dates[0], dates[-1]] if dates else None
            # look-through SPY desde etf_holdings/snapshots (mejor esfuerzo)
            try:
                eh = w.select_rows("etf_holdings", select="etf,ticker,weight",
                                   params={"etf": "eq.SPY", "order": "weight.desc", "limit": "50"})
                lt = {r["ticker"]: float(r["weight"]) for r in eh if r.get("ticker") and r.get("weight")}
                if lt:
                    lookthrough["SPY"] = lt
            except Exception:
                pass
        except Exception as e:
            out["aviso_datos"] = f"{type(e).__name__}: {str(e)[:120]}"
    if lookthrough:
        out["solape_economico"] = pr.economic_exposure(WEIGHTS, lookthrough)
    else:
        out["solape_economico"] = {"nota": "sin look-through de ETF disponible (etf_holdings)"}
    out["estres"] = pr.stress(WEIGHTS, rets, META, STRESS)

    if rets and all(len(rets.get(t, [])) > 60 for t in tickers):
        # recortar a longitud común mínima
        m = min(len(v) for v in rets.values())
        rets = {t: v[-m:] for t, v in rets.items()}
        out["volatilidad_anual"] = {t: round(pr.annualized_vol(rets[t]), 4) for t in tickers}
        out["contribucion_riesgo"] = pr.risk_contributions(WEIGHTS, rets)
        lvl = pr.portfolio_series(WEIGHTS, rets)
        out["drawdown_portafolio"] = pr.max_drawdown(lvl)
        if BENCH in rets:
            out["beta_benchmark"] = pr.portfolio_beta({t: WEIGHTS[t] for t in WEIGHTS if t != BENCH and t in rets},
                                                      rets, rets[BENCH])
        out["impacto_marginal_ejemplo"] = pr.marginal_impact(WEIGHTS, rets, "TSM", -0.10, META)
    else:
        out["nota_retornos"] = "sin retornos suficientes (requiere price_history vía Supabase)"
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--no-net", action="store_true")
    args = p.parse_args(argv)
    print(json.dumps(run(args.no_net), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
