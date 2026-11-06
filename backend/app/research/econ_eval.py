"""Evaluación económica CONFIRMATORIA de A y B frente a SPY y equiponderado.

Condiciones idénticas para las 4 estrategias (mismas fechas, mismo universo invertible):
  - SPY         : buy & hold (retorno de SPY entre fechas de rebalanceo; turnover ~0).
  - Equal-weight: cartera equiponderada del universo invertible, rebalanceada cada 20s.
  - Modelo A    : quintil superior por predicción de A (precio), equiponderado.
  - Modelo B    : quintil superior por predicción de B (precio+fundamentales PIT).

Regla de cartera (CONGELADA, fijada a priori — NO seleccionada por desempeño OOS):
  * Universo invertible en cada fecha d = nombres con features de precio válidas Y
    fundamentales PIT disponibles (filing_date<=d) Y retorno forward de 20 sesiones
    realizado. -> A y B eligen del MISMO conjunto (comparabilidad estricta).
  * Entrenamiento walk-forward PURGADO: en d solo se usan ejemplos cuyo retorno ya se
    realizó a d (realize<=d). Target de entrenamiento = retorno RELATIVO al equiponderado
    (idéntico al de la emisión congelada); el ranking selecciona el quintil superior.
  * Ponderación equiponderada dentro del quintil. Sin apalancamiento ni cortos.
  * Rebalanceo cada 20 sesiones NYSE, NO solapado (paso = horizonte) -> composición limpia.
  * Costo de transacción = turnover * cost_bps (sensibilidad a 0/5/10/20/50 bps).

El retorno de cada estrategia es ABSOLUTO (lo que realmente se gana), comparable con SPY.

Sesgos declarados: el universo parte de constituyentes actuales + Yahoo (los deslistados
desaparecen) => SURVIVORSHIP BIAS presente; NO puede eliminarse con datos gratuitos, se
declara explícitamente. OOS histórico (último 20%) YA fue consultado => no es holdout
virgen; la única validación prospectiva real es la emisión diaria (309 predicciones).

Uso: python -m app.research.econ_eval --range 15y
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional

from ..providers import get_provider
from ..jobs.universe import get_universe
from .features import (drawdown_from_high_at, momentum_12_1, reversal, trailing_return,
                       trailing_vol, volume_ratio)
from .abc_compare import load_prices, read_fundamentals, read_sectors, fund_features
from . import perf

STEP = 20
HORIZON = 20
PPY = 252 / STEP  # 12.6
COST_LEVELS_BPS = [0, 5, 10, 20, 50]
HEADLINE_BPS = 10


def _price_feats(closes, vols, dts, i, mkt, mdates, midx):
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


def build_panel(provider, writer, tickers):
    prices = load_prices(provider, tickers, rng="15y")
    spy_bars = provider.get_history_bars("SPY", rng="15y")
    spy = {x["as_of"]: x["close"] for x in spy_bars}
    funds = read_fundamentals(writer, list(prices.keys()))
    sectors = read_sectors(writer, list(prices.keys()))

    acc = defaultdict(list)
    for b in prices.values():
        c = [x["close"] for x in b]; dts = [x["as_of"] for x in b]
        for k in range(1, len(c)):
            if c[k - 1] > 0 and c[k] > 0:
                acc[dts[k]].append(math.log(c[k] / c[k - 1]))
    mkt = {d: sum(v) / len(v) for d, v in acc.items() if v}
    mdates = sorted(mkt); midx = {d: i for i, d in enumerate(mdates)}

    rows = []  # {date, ticker, A, fwd_abs, realize, sector, hasB, Bfeat}
    for t, b in prices.items():
        closes = [x["close"] for x in b]; vols = [x.get("volume") for x in b]; dts = [x["as_of"] for x in b]
        tl = funds.get(t, {}); sec = sectors.get(t, "Otro")
        for i in range(252, len(closes) - 1, STEP):
            if i + HORIZON >= len(closes) or closes[i] <= 0:
                continue
            fA = _price_feats(closes, vols, dts, i, mkt, mdates, midx)
            if fA is None:
                continue
            fwd_abs = closes[i + HORIZON] / closes[i] - 1.0
            fB = fund_features(tl, dts[i])
            rows.append({"date": dts[i], "ticker": t, "A": fA, "B": fB,
                         "fwd_abs": fwd_abs, "realize": dts[i + HORIZON], "sector": sec})
    return rows, spy


def _spy_ret(spy, d0, d1):
    # cierre SPY más cercano <= fecha, para alinear al calendario de rebalanceo
    def near(d):
        best = None
        for k in sorted(spy):
            if k <= d:
                best = spy[k]
            else:
                break
        return best
    a, b = near(d0), near(d1)
    return (b / a - 1.0) if (a and b and a > 0) else None


def run(provider, writer, tickers):
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    rows, spy = build_panel(provider, writer, tickers)
    # universo COMÚN A/B: solo filas con fundamentales disponibles
    common = [r for r in rows if r["B"] is not None]
    dates = sorted({r["date"] for r in common})
    if len(dates) < 30:
        return {"error": f"muestra común insuficiente ({len(common)} filas, {len(dates)} fechas)"}
    oos_start = dates[int(0.8 * len(dates))]

    # EW forward por fecha (para el target relativo, idéntico a la emisión)
    ew_fwd = {}
    for d in dates:
        day = [r["fwd_abs"] for r in common if r["date"] == d]
        ew_fwd[d] = sum(day) / len(day) if day else 0.0

    # series de retorno por estrategia (netas a cada nivel de costo) y turnover
    def X(rr, fund):
        return [(r["A"] + r["B"]) if fund else r["A"] for r in rr]

    series = {s: {c: [] for c in COST_LEVELS_BPS} for s in ["SPY", "EW", "A", "B"]}
    turn = {"EW": [], "A": [], "B": []}
    prev = {"EW": None, "A": None, "B": None}
    sector_sel = {"A": defaultdict(int), "B": defaultdict(int)}
    rebal_dates = []

    for di in range(12, len(dates)):
        d = dates[di]
        train = [r for r in common if r["realize"] <= d]
        test = [r for r in common if r["date"] == d]
        if len(train) < 100 or len(test) < 10:
            continue
        realize_d = test[0]["realize"]
        rebal_dates.append(d)
        ytr = np.array([r["fwd_abs"] - ew_fwd[r["date"]] for r in train])  # target RELATIVO
        # SPY y EW
        sp = _spy_ret(spy, d, realize_d)
        ewr = sum(r["fwd_abs"] for r in test) / len(test)
        ew_names = set(r["ticker"] for r in test)
        ew_to = 1.0 if prev["EW"] is None else len(ew_names ^ prev["EW"]) / max(1, len(ew_names | prev["EW"]))
        prev["EW"] = ew_names; turn["EW"].append(ew_to)
        # modelos
        baskets = {}
        for fam, fund in (("A", False), ("B", True)):
            sc = StandardScaler().fit(np.array(X(train, fund)))
            mdl = Ridge(alpha=1.0).fit(sc.transform(np.array(X(train, fund))), ytr)
            p = mdl.predict(sc.transform(np.array(X(test, fund)))).tolist()
            order = sorted(range(len(test)), key=lambda k: p[k], reverse=True)
            top = order[: max(1, len(order) // 5)]
            names = set(test[k]["ticker"] for k in top)
            to = 1.0 if prev[fam] is None else len(names ^ prev[fam]) / max(1, len(names | prev[fam]))
            prev[fam] = names; turn[fam].append(to)
            gross = sum(test[k]["fwd_abs"] for k in top) / len(top)
            baskets[fam] = (gross, to)
            for k in top:
                sector_sel[fam][test[k].get("sector", "Otro")] += 1
        # netear por nivel de costo
        for c in COST_LEVELS_BPS:
            cf = c / 10000.0
            series["SPY"][c].append(sp if sp is not None else 0.0)   # turnover SPY ~0
            series["EW"][c].append(ewr - ew_to * cf)
            series["A"][c].append(baskets["A"][0] - baskets["A"][1] * cf)
            series["B"][c].append(baskets["B"][0] - baskets["B"][1] * cf)

    if not rebal_dates:
        return {"error": "sin fechas de rebalanceo válidas"}

    # métricas por estrategia (headline = 10 bps) + a cada nivel de costo
    def strat_metrics(name):
        head = series[name][HEADLINE_BPS]
        tv = (sum(turn[name]) / len(turn[name])) if name in turn and turn[name] else 0.0
        m = perf.summarize(head, PPY, turnover=tv, cost_bps=HEADLINE_BPS)
        m["cost_sensitivity"] = {f"{c}bps": {
            "cum_return": round(perf.cumulative(series[name][c]), 4),
            "cagr": (round(perf.cagr(series[name][c], PPY), 4) if perf.cagr(series[name][c], PPY) is not None else None),
            "sharpe": (round(perf.sharpe(series[name][c], PPY), 3) if perf.sharpe(series[name][c], PPY) is not None else None),
        } for c in COST_LEVELS_BPS}
        return m

    strategies = {name: strat_metrics(name) for name in ["SPY", "EW", "A", "B"]}
    head = {name: series[name][HEADLINE_BPS] for name in series}

    # significancia (headline 10 bps): exceso vs EW y vs SPY, y A vs B
    comps = {
        "A_vs_EW": perf.vs_benchmark(head["A"], head["EW"], PPY),
        "B_vs_EW": perf.vs_benchmark(head["B"], head["EW"], PPY),
        "A_vs_SPY": perf.vs_benchmark(head["A"], head["SPY"], PPY),
        "B_vs_SPY": perf.vs_benchmark(head["B"], head["SPY"], PPY),
        "A_vs_B": perf.vs_benchmark(head["A"], head["B"], PPY),
    }
    # corrección por comparaciones múltiples (Holm) sobre los p-valores de exceso
    pvals = [(k, v["excess_p_value"]) for k, v in comps.items() if v["excess_p_value"] is not None]
    pvals.sort(key=lambda x: x[1])
    mtest = len(pvals)
    holm = {}
    for rank, (k, p) in enumerate(pvals):
        adj = min(1.0, p * (mtest - rank))
        holm[k] = {"p_raw": p, "p_holm": round(adj, 4), "sig_holm_0.10": bool(adj < 0.10)}

    return {
        "experimental": True, "status": "EVALUACIÓN ECONÓMICA — SIN VALIDAR",
        "ppy": round(PPY, 2), "rebalances": len(rebal_dates),
        "universe_common": len({r["ticker"] for r in common}),
        "first_date": rebal_dates[0], "last_date": rebal_dates[-1],
        "years": round(_ydiff(rebal_dates[0], rebal_dates[-1]), 1),
        "oos_start_consulted": oos_start,
        "portfolio_rule": {
            "selection": "quintil superior por predicción", "weighting": "equiponderado",
            "rebalance_sessions": STEP, "horizon_sessions": HORIZON, "overlap": "no (paso=horizonte)",
            "long_short": "solo largos", "train_target": "retorno relativo al equiponderado (congelado)",
            "alpha": 1.0, "costs_bps_tested": COST_LEVELS_BPS, "headline_cost_bps": HEADLINE_BPS,
        },
        "strategies": strategies,
        "comparisons_10bps": comps,
        "multiple_comparison_holm": holm,
        "sector_exposure": {fam: {k: round(v / max(1, sum(sector_sel[fam].values())), 3)
                                  for k, v in sorted(sector_sel[fam].items(), key=lambda x: -x[1])[:6]}
                            for fam in ("A", "B")},
        "biases": {
            "survivorship": "PRESENTE y no eliminable con datos gratuitos (universo = constituyentes "
                            "actuales + Yahoo; los deslistados desaparecen). Sesga al alza.",
            "oos_historico": "El último 20% YA fue consultado en corridas previas; no es holdout virgen.",
            "prospective": "La única validación prospectiva real es la emisión diaria (309 predicciones), "
                           "aún sin madurar.",
            "rf": "Sharpe/Sortino con tasa libre de riesgo = 0 (supuesto explícito).",
        },
    }


def _ydiff(a, b):
    from datetime import date
    ya, ma, da = map(int, a.split("-")); yb, mb, db = map(int, b.split("-"))
    return (date(yb, mb, db) - date(ya, ma, da)).days / 365.0


def main(argv=None):
    import random
    random.seed(42)
    p = argparse.ArgumentParser()
    p.add_argument("--range", default="15y")
    p.add_argument("--tickers", nargs="*")
    args = p.parse_args(argv)
    tickers = [t.upper() for t in args.tickers] if args.tickers else [i.ticker for i in get_universe(include_etfs=False)]
    from ..jobs.supabase_writer import SupabaseWriter
    writer = SupabaseWriter(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    try:
        out = run(get_provider("yahoo"), writer, tickers)
    except Exception as e:
        import traceback
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300], "tb": traceback.format_exc()[-900:]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
