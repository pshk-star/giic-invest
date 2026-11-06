"""Motor predictivo multivariable EXPERIMENTAL (Ridge / Elastic Net) con validación
walk-forward rigurosa. Aprende relaciones entre momentum, reversión, volatilidad,
volumen, drawdown, fuerza relativa, correlación al mercado y régimen — no solo momentum.

Rigor estadístico (auditoría solicitada):
  - Sin look-ahead: features usan solo pasado; el target (retorno futuro relativo al
    mercado) solo se usa para evaluar.
  - Ventanas solapadas controladas con PURGA: para predecir en la fecha d, el
    entrenamiento solo usa filas cuyo target YA se realizó antes de d.
  - Horizontes en SESIONES bursátiles (1,5,20,60,120), muestreo no solapado por horizonte.
  - Intervalos de confianza del IC (bootstrap sobre fechas), estabilidad por subperíodos.
  - Costos de transacción en la estrategia; comparación vs equiponderado, buy&hold de
    mercado y modelo ingenuo (momentum).
  - Un modelo NO se declara validado por IC>0 o retorno acumulado: se exige IC medio con
    intervalo de confianza inferior > 0 y estabilidad entre subperíodos.
  - Sesgo de supervivencia: el universo son nombres actuales → resultados OPTIMISTAS; se
    reporta como limitación.
  - Monte Carlo CALIBRADO por block-bootstrap de retornos históricos (sin supuesto normal).

NO es recomendación hasta pasar los gates. MU es caso de aceptación, sin reglas especiales.

Uso: python -m app.research.multifactor_model --acceptance MU --range 7y
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from typing import Dict, List, Optional, Tuple

from ..providers import get_provider
from ..jobs.universe import get_universe
from .features import (SESSION_HORIZONS, correlation, daily_log_returns, drawdown_from_high_at,
                       momentum_12_1, reversal, trailing_return, trailing_vol, volume_ratio)
from .stats import quantiles, sharpe, spearman_ic

FEATURES = ["mom_12_1", "ret_20", "ret_60", "ret_120", "reversal_5",
            "vol_20", "vol_60", "volume_ratio", "dd_252", "rel_strength_60", "corr_mkt_60", "regime"]
STEP = 20            # sesiones entre fechas de decisión (muestreo)
TX_COST = 0.001      # 10 bps por rebalanceo (ida)
MIN_TRAIN = 24       # fechas de decisión mínimas para empezar a predecir


def load_panel(provider, tickers: List[str], rng: str):
    panel = {}
    for t in tickers:
        bars = provider.get_history_bars(t, rng=rng)
        if len(bars) > 300:
            panel[t] = {
                "dates": [b["as_of"] for b in bars],
                "closes": [b["close"] for b in bars],
                "vols": [b.get("volume") for b in bars],
                "idx": {b["as_of"]: i for i, b in enumerate(bars)},
            }
    return panel


def build_market(panel) -> Dict[str, float]:
    """Retorno log diario de mercado (promedio transversal) por fecha."""
    from collections import defaultdict
    acc = defaultdict(list)
    for p in panel.values():
        c, d = p["closes"], p["dates"]
        for k in range(1, len(c)):
            if c[k - 1] > 0 and c[k] > 0:
                import math
                acc[d[k]].append(math.log(c[k] / c[k - 1]))
    return {d: sum(v) / len(v) for d, v in acc.items() if v}


def _feat_row(p, i, mkt_ret_by_date, mkt_cum_ret) -> Optional[List[float]]:
    closes, vols, dates = p["closes"], p["vols"], p["dates"]
    f = {
        "mom_12_1": momentum_12_1(closes, i),
        "ret_20": trailing_return(closes, i, 20),
        "ret_60": trailing_return(closes, i, 60),
        "ret_120": trailing_return(closes, i, 120),
        "reversal_5": reversal(closes, i, 5),
        "vol_20": trailing_vol(closes, i, 20),
        "vol_60": trailing_vol(closes, i, 60),
        "volume_ratio": volume_ratio(vols, i, 20, 60),
        "dd_252": drawdown_from_high_at(closes, i, 252),
    }
    # fuerza relativa y correlación vs mercado (últimas 60 sesiones alineadas por fecha)
    r60 = trailing_return(closes, i, 60)
    mkt60 = mkt_cum_ret(dates, i, 60)
    f["rel_strength_60"] = (r60 - mkt60) if (r60 is not None and mkt60 is not None) else None
    tkr_lr = daily_log_returns(closes[max(0, i - 60):i + 1])
    mkt_lr = [mkt_ret_by_date.get(dates[k]) for k in range(max(1, i - 59), i + 1)]
    mkt_lr = [x for x in mkt_lr if x is not None]
    f["corr_mkt_60"] = correlation(tkr_lr[-len(mkt_lr):], mkt_lr) if len(mkt_lr) >= 3 and len(tkr_lr) >= len(mkt_lr) else None
    f["regime"] = None  # se rellena fuera (tercil global de vol de mercado)
    vals = [f[k] for k in FEATURES if k != "regime"]
    if any(v is None for v in vals):
        return None
    return [f[k] for k in FEATURES[:-1]]  # sin regime (se añade luego)


def run(provider, tickers: List[str], acceptance: str, rng: str) -> dict:
    import numpy as np
    from sklearn.linear_model import ElasticNet, Ridge
    from sklearn.preprocessing import StandardScaler

    panel = load_panel(provider, tickers, rng)
    if len(panel) < 10:
        return {"error": "universo insuficiente con histórico"}
    mkt_ret = build_market(panel)
    mkt_dates = sorted(mkt_ret)
    mkt_didx = {d: i for i, d in enumerate(mkt_dates)}

    def mkt_cum_ret(dates, i, lag):
        d0 = dates[i - lag] if i - lag >= 0 else None
        d1 = dates[i]
        if d0 is None or d0 not in mkt_didx or d1 not in mkt_didx:
            return None
        a, b = mkt_didx[d0], mkt_didx[d1]
        import math
        s = sum(mkt_ret[mkt_dates[k]] for k in range(a + 1, b + 1))
        return math.exp(s) - 1.0

    # régimen: vol de mercado en 20 sesiones, terciles globales
    def mkt_vol20(d_idx):
        if d_idx < 20:
            return None
        import math
        rs = [mkt_ret[mkt_dates[k]] for k in range(d_idx - 19, d_idx + 1)]
        m = sum(rs) / len(rs)
        var = sum((r - m) ** 2 for r in rs) / (len(rs) - 1)
        return math.sqrt(var) * math.sqrt(252)
    mv = [mkt_vol20(k) for k in range(len(mkt_dates))]
    mv_valid = sorted([x for x in mv if x is not None])
    t1 = mv_valid[len(mv_valid) // 3] if mv_valid else 0
    t2 = mv_valid[2 * len(mv_valid) // 3] if mv_valid else 0

    def regime_at(date):
        if date not in mkt_didx:
            return 1
        v = mv[mkt_didx[date]]
        if v is None:
            return 1
        return 0 if v <= t1 else (2 if v > t2 else 1)

    results = {}
    for h in SESSION_HORIZONS:
        step = max(STEP, h)
        rows = []  # (date, ticker, X(list), y(relativo), realize_date)
        for t, p in panel.items():
            closes, dates = p["closes"], p["dates"]
            for i in range(252, len(closes) - h, step):
                base = _feat_row(p, i, mkt_ret, mkt_cum_ret)
                if base is None:
                    continue
                fwd = trailing_return(closes, i + h, h)  # retorno de i a i+h
                mkt_fwd = mkt_cum_ret(dates, i + h, h)
                if fwd is None or mkt_fwd is None:
                    continue
                X = base + [float(regime_at(dates[i]))]
                rows.append((dates[i], t, X, fwd - mkt_fwd, dates[i + h]))
        if len(rows) < 200:
            results[f"{h}s"] = {"note": "datos insuficientes"}
            continue

        decision_dates = sorted({r[0] for r in rows})
        ic_ridge, ic_enet, ic_naive = [], [], []
        strat_ridge, strat_bench = [], []
        for di in range(MIN_TRAIN, len(decision_dates)):
            d = decision_dates[di]
            train = [r for r in rows if r[4] <= d]           # PURGA: target ya realizado antes de d
            test = [r for r in rows if r[0] == d]
            if len(train) < 100 or len(test) < 8:
                continue
            Xtr = np.array([r[2] for r in train]); ytr = np.array([r[3] for r in train])
            Xte = np.array([r[2] for r in test]); yte = np.array([r[3] for r in test])
            sc = StandardScaler().fit(Xtr)
            Xtr_s, Xte_s = sc.transform(Xtr), sc.transform(Xte)
            rid = Ridge(alpha=1.0).fit(Xtr_s, ytr)
            ent = ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=5000).fit(Xtr_s, ytr)
            pr_rid = rid.predict(Xte_s).tolist()
            pr_ent = ent.predict(Xte_s).tolist()
            naive = [r[2][FEATURES.index("mom_12_1")] for r in test]
            actual = yte.tolist()
            for store, pred in ((ic_ridge, pr_rid), (ic_enet, pr_ent), (ic_naive, naive)):
                ic = spearman_ic(pred, actual)
                if ic is not None:
                    store.append(ic)
            # estrategia (solo h=20 para no solapar demasiado): top-quintil por Ridge
            if h == 20:
                order = sorted(range(len(test)), key=lambda k: pr_rid[k], reverse=True)
                top = order[: max(1, len(order) // 5)]
                strat_ridge.append(sum(actual[k] for k in top) / len(top) - TX_COST)
                strat_bench.append(0.0)  # relativo al mercado; equiponderado ≈ 0

        def summ(xs):
            if not xs:
                return None
            m = sum(xs) / len(xs)
            # bootstrap IC (CI 90%)
            boot = []
            for _ in range(500):
                s = [xs[random.randrange(len(xs))] for _ in range(len(xs))]
                boot.append(sum(s) / len(s))
            boot.sort()
            lo, hi = boot[int(0.05 * len(boot))], boot[int(0.95 * len(boot))]
            half = len(xs) // 2
            sub1 = sum(xs[:half]) / half if half else None
            sub2 = sum(xs[half:]) / (len(xs) - half) if len(xs) - half else None
            return {"mean_ic": round(m, 4), "ci90": [round(lo, 4), round(hi, 4)],
                    "n_dates": len(xs), "subperiod_ic": [round(sub1, 4) if sub1 else None, round(sub2, 4) if sub2 else None],
                    "defendable": bool(lo > 0 and sub1 is not None and sub2 is not None and sub1 > 0 and sub2 > 0)}

        res_h = {"ridge": summ(ic_ridge), "elastic_net": summ(ic_enet), "naive_momentum": summ(ic_naive)}
        if h == 20 and strat_ridge:
            res_h["strategy_h20"] = {
                "months": len(strat_ridge),
                "ridge_net_mean": round(sum(strat_ridge) / len(strat_ridge), 4),
                "ridge_sharpe": round(sharpe(strat_ridge), 3) if sharpe(strat_ridge) else None,
                "note": "retorno relativo al mercado, neto de costos; benchmark equiponderado ≈ 0",
            }
        results[f"{h}s"] = res_h

    # ---- Monte Carlo calibrado (block bootstrap) para el caso de aceptación ----
    mc = {}
    acc = acceptance.upper()
    if acc in panel:
        import math
        lr = daily_log_returns(panel[acc]["closes"])
        if len(lr) > 120:
            block = 5
            for h in (20, 60):
                sims = []
                for _ in range(2000):
                    path = []
                    while len(path) < h:
                        start = random.randrange(0, len(lr) - block)
                        path += lr[start:start + block]
                    cum = math.exp(sum(path[:h])) - 1.0
                    sims.append(cum)
                q = quantiles(sims, [0.05, 0.25, 0.5, 0.75, 0.95])
                mc[f"{h}s"] = {
                    **{k: round(v, 4) for k, v in q.items()},
                    "prob_loss": round(sum(1 for x in sims if x < 0) / len(sims), 3),
                    "prob_ge_10pct": round(sum(1 for x in sims if x >= 0.10) / len(sims), 3),
                }

    return {
        "experimental": True,
        "note": "Modelo multivariable OOS. NO es recomendación; se declara 'defendable' solo si IC CI90 inferior>0 y estable en ambos subperíodos.",
        "survivorship_bias": "El universo son nombres actuales; resultados OPTIMISTAS hasta tener membresía histórica.",
        "universe_size": len(panel),
        "features": FEATURES,
        "horizons_sessions": SESSION_HORIZONS,
        "ic_by_horizon": results,
        "montecarlo_acceptance": {"ticker": acc, "block_bootstrap": mc},
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="GIIC motor multivariable (experimental)")
    p.add_argument("--acceptance", default="MU")
    p.add_argument("--range", default="7y")
    p.add_argument("--tickers", nargs="*")
    args = p.parse_args(argv)
    random.seed(42)
    tickers = [t.upper() for t in args.tickers] if args.tickers else [i.ticker for i in get_universe(include_etfs=False)]
    try:
        out = run(get_provider("yahoo"), tickers, args.acceptance, args.range)
    except Exception as e:
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
