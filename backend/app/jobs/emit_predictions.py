"""Emisión PROSPECTIVA EXPERIMENTAL (origin='production') de los modelos congelados A y B.

NO es una recomendación. Cada fila lleva data_ref.status = EXPERIMENTAL_NO_VALIDADO.
Se entrena con historia PIT purgada (solo ejemplos ya realizados a la fecha de emisión D)
y se predice la sección transversal de D para:
    A @ {20, 60, 252} sesiones  (benchmark experimental)
    B @ {252} sesiones          (candidato experimental, SIN superioridad probada)

Inmutabilidad + idempotencia:
  - run_id DETERMINISTA = "<model_version>:<D>" -> reemitir el mismo día no duplica
    (insert ON CONFLICT DO NOTHING sobre predictions_uniq_origin_run).
  - El índice parcial predictions_one_official_production impide una SEGUNDA emisión
    oficial distinta para el mismo (modelo, versión, ticker, as_of, horizonte).
  - evaluate_on se calcula con el calendario OFICIAL NYSE/Nasdaq (no con price_history).

Seguridad: no imprime secretos; aborta si algún valor serializado contuviera la service key.

Uso:
    python -m app.jobs.emit_predictions --range 15y [--tickers AAPL MSFT ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional

from ..providers import get_provider
from ..jobs.universe import get_universe
from ..research import us_market_calendar as cal
from ..research.calendar import evaluate_on
from ..research.features import (drawdown_from_high_at, momentum_12_1, reversal,
                                 trailing_return, trailing_vol, volume_ratio)
from ..research.abc_compare import load_prices, read_fundamentals, read_sectors, fund_features
from ..research.model_spec import (CALENDAR, FEATURES_VERSION, MODEL_A, MODEL_B, STATUS)


def _d(s: str) -> date:
    y, m, dd = map(int, s.split("-")); return date(y, m, dd)


def price_features_at(closes, vols, dts, i, mkt, mdates, midx) -> Optional[list]:
    """Las 10 features de precio congeladas (PRICE_FEATURES), en orden, en el índice i."""
    def mkt_cum(lag):
        if i - lag < 0:
            return None
        d0, d1 = dts[i - lag], dts[i]
        if d0 not in midx or d1 not in midx:
            return None
        return math.exp(sum(mkt[mdates[k]] for k in range(midx[d0] + 1, midx[d1] + 1))) - 1.0
    r60 = trailing_return(closes, i, 60); m60 = mkt_cum(60)
    rel = (r60 - m60) if (r60 is not None and m60 is not None) else None
    f = [momentum_12_1(closes, i), trailing_return(closes, i, 20), trailing_return(closes, i, 60),
         trailing_return(closes, i, 120), reversal(closes, i, 5), trailing_vol(closes, i, 20),
         trailing_vol(closes, i, 60), drawdown_from_high_at(closes, i, 252), volume_ratio(vols, i, 20, 60), rel]
    return None if any(x is None for x in f) else f


def build(provider, writer, tickers, rng):
    prices = load_prices(provider, tickers, rng)
    if len(prices) < 10:
        return None, None, "universo insuficiente"
    funds = read_fundamentals(writer, list(prices.keys()))
    sectors = read_sectors(writer, list(prices.keys()))

    # Mercado equiponderado (log-retornos) para el target relativo y la feature rel_strength.
    acc = defaultdict(list)
    for b in prices.values():
        c = [x["close"] for x in b]; dts = [x["as_of"] for x in b]
        for k in range(1, len(c)):
            if c[k - 1] > 0 and c[k] > 0:
                acc[dts[k]].append(math.log(c[k] / c[k - 1]))
    mkt = {d: sum(v) / len(v) for d, v in acc.items() if v}
    mdates = sorted(mkt); midx = {d: i for i, d in enumerate(mdates)}
    D = mdates[-1]  # fecha de emisión = última sesión con mercado

    def mkt_cum(dts, i, lag):
        if i - lag < 0:
            return None
        d0, d1 = dts[i - lag], dts[i]
        if d0 not in midx or d1 not in midx:
            return None
        return math.exp(sum(mkt[mdates[k]] for k in range(midx[d0] + 1, midx[d1] + 1))) - 1.0

    HS = [20, 60, 252]
    # train[h] = lista de ejemplos ya REALIZADOS a D (sin look-ahead); pred = sección de D.
    train = {h: [] for h in HS}
    pred = {}  # ticker -> {"A":[...], "B":[...]|None, "sector":...}
    for t, b in prices.items():
        closes = [x["close"] for x in b]; vols = [x.get("volume") for x in b]; dts = [x["as_of"] for x in b]
        tl = funds.get(t, {}); sec = sectors.get(t, "Otro")
        # ejemplos de entrenamiento (grilla mensual, con forward realizado)
        for i in range(252, len(closes) - 1, 20):
            fA = price_features_at(closes, vols, dts, i, mkt, mdates, midx)
            if fA is None:
                continue
            fB = fund_features(tl, dts[i])
            for h in HS:
                if i + h < len(closes) and closes[i] > 0:
                    mf = mkt_cum(dts, i + h, h)
                    if mf is not None and dts[i + h] <= D:
                        y = closes[i + h] / closes[i] - 1.0 - mf
                        train[h].append({"A": fA, "B": fB, "y": y})
        # sección transversal de D (features en la última sesión == D)
        if dts and dts[-1] == D:
            i = len(closes) - 1
            fA = price_features_at(closes, vols, dts, i, mkt, mdates, midx)
            if fA is not None:
                pred[t] = {"A": fA, "B": fund_features(tl, D), "sector": sec}
    return {"D": D, "mdates": mdates, "train": train, "pred": pred}, None, None


def _fit_predict(train_rows, pred_names, pred_feat, use_fund):
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    def vec(r):
        return (r["A"] + r["B"]) if use_fund else r["A"]
    tr = [r for r in train_rows if (not use_fund or r["B"] is not None)]
    names = [t for t in pred_names if (not use_fund or pred_feat[t]["B"] is not None)]
    if len(tr) < 80 or len(names) < 8:
        return None, len(tr), len(names)
    Xtr = np.array([vec(r) for r in tr]); ytr = np.array([r["y"] for r in tr])
    sc = StandardScaler().fit(Xtr)
    mdl = Ridge(alpha=1.0).fit(sc.transform(Xtr), ytr)
    Xte = np.array([vec(pred_feat[t]) for t in names])
    p = mdl.predict(sc.transform(Xte)).tolist()
    order = sorted(range(len(names)), key=lambda k: p[k])
    rank = {order[k]: (k + 0.5) / len(names) for k in range(len(names))}  # percentil ascendente
    return {names[k]: {"rel_return": round(float(p[k]), 6), "pct_rank": round(rank[k], 4),
                       "n_cross_section": len(names)} for k in range(len(names))}, len(tr), len(names)


def emit(data, dry_run: bool, writer, service_key: str) -> dict:
    D = data["D"]; pred = data["pred"]; train = data["train"]
    # calendario oficial para evaluate_on (hasta ~1.5 años para alcanzar 252 sesiones futuras)
    sess = cal.sessions(_d(D) - timedelta(days=5), _d(D) + timedelta(days=430))
    now = _utcnow()
    plan = [(MODEL_A, 20, False), (MODEL_A, 60, False), (MODEL_A, 252, False), (MODEL_B, 252, True)]
    rows: List[dict] = []
    summary = {"as_of": D, "emitted_at": now, "status": STATUS, "models": []}
    for model, h, use_fund in plan:
        preds, n_tr, n_names = _fit_predict(train[h], list(pred.keys()), pred, use_fund)
        eo = evaluate_on(sess, D, h)
        entry = {"model": model["name"], "version": model["version"], "horizon_sessions": h,
                 "evaluate_on": eo, "n_train": n_tr, "n_cross_section": n_names,
                 "emitted": 0}
        if preds is None or eo is None:
            entry["note"] = "sin datos suficientes o sin sesión de evaluación"
            summary["models"].append(entry); continue
        run_id = f"{model['version']}:{D}"
        data_ref = {"price_source": "yahoo", "price_asof": D, "features_version": FEATURES_VERSION,
                    "feature_set": model["feature_set"], "estimator": model["estimator"],
                    "status": STATUS, "n_train": n_tr, "train_horizon_sessions": h,
                    "universe_size": n_names, "calendar": CALENDAR,
                    "note": "EXPERIMENTAL / NO VALIDADO. No es recomendación de inversión."}
        for t, pv in preds.items():
            rows.append({
                "model_name": model["name"], "model_version": model["version"],
                "features_version": FEATURES_VERSION, "ticker": t, "as_of": D,
                "horizon_sessions": h, "benchmark": "equal_weight_market",
                "prediction": pv, "evaluate_on": eo, "origin": "production",
                "emitted_at": now, "calendar": CALENDAR, "run_id": run_id, "data_ref": data_ref,
            })
        entry["emitted"] = len(preds); entry["run_id"] = run_id
        summary["models"].append(entry)

    # seguridad: ninguna fila debe contener la service key
    blob = json.dumps(rows)
    if service_key and service_key in blob:
        raise RuntimeError("ABORT: secret leak detected in prediction rows")
    summary["total_rows"] = len(rows)
    if dry_run:
        summary["dry_run"] = True
        return summary
    writer.insert_append("predictions", rows,
                         on_conflict="origin,model_name,model_version,run_id,ticker,as_of,horizon_sessions")
    # confirmación: leer de vuelta lo almacenado para esta fecha/producción
    stored = writer.select_rows("predictions", select="model_name,model_version,horizon_sessions,ticker",
                                params={"origin": "eq.production", "as_of": f"eq.{D}"})
    by = defaultdict(set)
    for r in stored:
        by[(r["model_name"], r["model_version"], r["horizon_sessions"])].add(r["ticker"])
    summary["stored_confirm"] = {f"{k[0]} {k[1]} @{k[2]}s": len(v) for k, v in sorted(by.items())}
    summary["stored_total"] = len(stored)
    return summary


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def main(argv=None):
    import random
    random.seed(42)
    p = argparse.ArgumentParser()
    p.add_argument("--range", default="15y")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    tickers = [t.upper() for t in args.tickers] if args.tickers else [i.ticker for i in get_universe(include_etfs=False)]
    url = os.getenv("SUPABASE_URL", ""); key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from ..jobs.supabase_writer import SupabaseWriter
    writer = SupabaseWriter(url, key)
    try:
        data, _, err = build(get_provider("yahoo"), writer, tickers, args.range)
        if err:
            print(json.dumps({"error": err})); return 1
        out = emit(data, args.dry_run, writer, key)
    except Exception as e:
        import traceback
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300], "tb": traceback.format_exc()[-900:]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
