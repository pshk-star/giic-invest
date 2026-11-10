"""P1.8 — BACKTEST point-in-time de los modelos de proyección (A/C/D) contra resultados reportados.

Para cada empresa reconstruye la serie anual reportada (EODHD, un fetch por ticker) y, para cada año
base ti con ≥4 años previos y actual disponible a ti+h, proyecta con A/C/D usando SOLO datos ≤ ti y
compara ingresos, margen EBIT y FCFF con lo efectivamente reportado en ti+h. Sin look-ahead; sin
consenso (B no tiene vintages históricos). Convención de disponibilidad: FY(ti) disponible a
FY_end+90d (no afecta la comparación reportado-vs-reportado, que ya respeta ti).

Métricas por modelo×horizonte: MAE (mediana |error rel|), sesgo (mediana error rel), N, por empresa
y sector. Cobertura de intervalos 50/80/90% por jackknife (leave-one-out) sobre la distribución de
errores OOS. Si la muestra es pequeña, se reporta N y se marca 'insuficiente'.

Uso: python -m app.research.forecast_backtest [--universe N]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from statistics import median
from typing import Dict, List, Optional

from .forecast_models import project, rel_error, taxrate, _reinvestment, sales_to_capital

FIVE = ["NVDA", "META", "NFLX", "TSM", "ASML"]
RF_BY_CCY = {"USD": 0.041, "EUR": 0.026, "TWD": 0.015}
FX_USD = {"USD": 1.0, "EUR": 1.1203, "TWD": 1 / 32.80}   # para MAE en moneda normalizada (USD)
MIN_SAMPLE = 20   # por debajo de esto no se declaran intervalos calibrados


def build_series(by_field: dict) -> List[dict]:
    """Serie anual ordenada con revenue, ebit, ebit_margin, pretax, tax, capex, dna, wc_change."""
    rev = by_field.get("revenue", {}) or {}
    periods = sorted(rev.keys())
    out = []
    for p in periods:
        r = {"year": p, "revenue": rev.get(p),
             "ebit": (by_field.get("operating_income", {}) or {}).get(p),
             "pretax": (by_field.get("pretax", {}) or {}).get(p),
             "tax": (by_field.get("tax", {}) or {}).get(p),
             "capex": (by_field.get("capex", {}) or {}).get(p),
             "dna": (by_field.get("dna", {}) or {}).get(p),
             "wc_change": (by_field.get("wc_change", {}) or {}).get(p)}
        if r["revenue"] and r["revenue"] > 0 and r["ebit"] is not None:
            r["ebit_margin"] = r["ebit"] / r["revenue"]
            out.append(r)
    return out


def actual_fcff(series: List[dict], j: int) -> Optional[float]:
    r = series[j]
    if r.get("ebit") is None:
        return None
    tr = taxrate(series, j)
    ri = _reinvestment(r)
    if ri is None:
        return None
    return r["ebit"] * (1 - tr) - ri


def backtest_company(ticker: str, ccy: str, series: List[dict], sector: str = "Otro",
                     horizons=(1, 2, 3)) -> List[dict]:
    gT = RF_BY_CCY.get(ccy, 0.041)
    fx = FX_USD.get(ccy, 1.0)
    pts = []
    n = len(series)
    for ti in range(4, n - 1):
        for model in ("A", "C", "D"):
            proj = project(model, series, ti, gT, horizons)
            for h in horizons:
                j = ti + h
                if j >= n or proj.get(h) is None:
                    continue
                a_rev = series[j]["revenue"]; a_m = series[j].get("ebit_margin")
                a_ebit = series[j].get("ebit"); a_reinv = _reinvestment(series[j])
                a_fcff = actual_fcff(series, j)
                f = proj[h]
                pts.append({
                    "ticker": ticker, "ccy": ccy, "sector": sector, "fx_usd": fx,
                    "base_year": series[ti]["year"], "target_year": series[j]["year"],
                    "model": model, "h": h,
                    # crudos por componente (predicho / real), en moneda local
                    "rev_f": f["revenue"], "rev_a": a_rev,
                    "margin_f": f.get("ebit_margin"), "margin_a": a_m,
                    "ebit_f": f.get("ebit"), "ebit_a": a_ebit,
                    "reinv_f": f.get("reinvest"), "reinv_a": a_reinv,
                    "fcff_f": f.get("fcff"), "fcff_a": a_fcff,
                    # error relativo heredado (para continuidad con P1.8)
                    "err_rev": rel_error(f["revenue"], a_rev),
                    "err_margin": (f.get("ebit_margin") - a_m) if (f.get("ebit_margin") is not None and a_m is not None) else None,
                    "err_fcff": rel_error(f["fcff"], a_fcff),
                })
    return pts


def _agg(errs: List[float]) -> dict:
    e = [x for x in errs if x is not None]
    if not e:
        return {"n": 0}
    ae = sorted(abs(x) for x in e)
    return {"n": len(e), "mae": round(median(ae), 4), "bias": round(median(e), 4),
            "p90_abs": round(ae[min(len(ae) - 1, int(0.9 * len(ae)))], 4)}


def jackknife_coverage(errs: List[float], levels=(0.5, 0.8, 0.9)) -> dict:
    e = [x for x in errs if x is not None]
    out = {"n": len(e)}
    if len(e) < MIN_SAMPLE:
        out["suficiente"] = False
        return out
    out["suficiente"] = True
    for p in levels:
        hits = 0
        for i in range(len(e)):
            others = sorted(abs(e[k]) for k in range(len(e)) if k != i)
            hw = others[min(len(others) - 1, int(p * len(others)))]
            if abs(e[i]) <= hw:
                hits += 1
        out[f"cov_{int(p*100)}"] = round(hits / len(e), 3)
    return out


def summarize(all_pts: List[dict]) -> dict:
    by_mh = defaultdict(lambda: defaultdict(list))   # (model,h) -> metric -> errs
    by_company = defaultdict(list)
    for p in all_pts:
        key = (p["model"], p["h"])
        by_mh[key]["rev"].append(p["err_rev"]); by_mh[key]["margin"].append(p["err_margin"])
        by_mh[key]["fcff"].append(p["err_fcff"])
        if p["model"] == "A":
            by_company[p["ticker"]].append(p["err_rev"])
    models = {}
    for (model, h), mt in sorted(by_mh.items()):
        models[f"{model}_h{h}"] = {"revenue": _agg(mt["rev"]), "margin": _agg(mt["margin"]),
                                   "fcff": _agg(mt["fcff"]),
                                   "coverage_revenue": jackknife_coverage(mt["rev"])}
    comp = {t: _agg(e) for t, e in sorted(by_company.items())}
    return {"by_model_horizon": models, "by_company_revenueA": comp,
            "total_points": len(all_pts)}


def run(tickers: List[str], dump_path: Optional[str] = None) -> dict:
    key = os.getenv("EODHD_API_KEY", "")
    if not key:
        return {"error": "sin EODHD_API_KEY"}
    from app.core.connectors.eodhd import EodhdFundamentalsConnector, eodhd_annual_series_full
    conn = EodhdFundamentalsConnector(api_key=key)
    all_pts: List[dict] = []
    meta = {}
    for t in tickers:
        try:
            _s, _a, obj = conn._resolve(t)
            if not obj:
                meta[t] = "sin objeto"; continue
            ser = build_series(eodhd_annual_series_full(obj).get("by_field", {}))
            gen = obj.get("General", {}) or {}
            ccy = gen.get("CurrencyCode", "USD"); sector = gen.get("Sector") or "Otro"
            if len(ser) < 6:
                meta[t] = f"serie corta ({len(ser)})"; continue
            pts = backtest_company(t, ccy, ser, sector, (1, 2, 3))
            all_pts.extend(pts)
            meta[t] = {"years": [ser[0]["year"][:4], ser[-1]["year"][:4]], "points": len(pts)}
        except Exception as e:
            meta[t] = f"{type(e).__name__}: {str(e)[:80]}"
    if dump_path:
        with open(dump_path, "w") as fh:
            json.dump({"points": all_pts, "meta": meta}, fh, default=str)
    return {"experimental": True, "sin_consenso_B": "EODHD no versiona consenso histórico (sin vintages)",
            "convencion_disponibilidad": "FY disponible a FY_end+90d; comparación reportado-vs-reportado",
            "muestra_minima_para_intervalos": MIN_SAMPLE, "cobertura_tickers": meta,
            "n_puntos_crudos": len(all_pts), "dump": dump_path,
            "resumen": summarize(all_pts)}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--universe", type=int, default=0, help="añade N tickers del universo a las 5")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--dump", default=None, help="ruta JSON para volcar los puntos crudos")
    args = p.parse_args(argv)
    tickers = [t.upper() for t in args.tickers] if args.tickers else list(FIVE)
    if args.universe:
        try:
            from app.jobs.universe import get_universe
            extra = [i.ticker for i in get_universe(include_etfs=False) if i.ticker not in tickers]
            tickers += extra[: args.universe]
        except Exception:
            pass
    print(json.dumps(run(tickers, dump_path=args.dump), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
