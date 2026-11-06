"""Forecasting EXPERIMENTAL — validación walk-forward, benchmarks y distribuciones
condicionales de retorno. SIN librerías de ML todavía: benchmarks + señal de momentum
(12-1) + análisis de episodios de caída/recuperación. Todo fuera de muestra, sin usar
información futura y sin inventar probabilidades (las distribuciones son EMPÍRICAS).

Caso de aceptación: MU (sin reglas especiales — se le aplican las mismas funciones).

Uso:
    python -m app.research.backtest                 # universo del scanner, imprime métricas
    python -m app.research.backtest --acceptance MU --range 5y

Importante: esto NO es una recomendación. Es una evaluación de si una señal simple tiene
poder predictivo fuera de muestra. Un modelo se "activa" solo si demuestra IC/retornos
fuera de muestra reproducibles.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List

from ..providers import get_provider
from .stats import (drawdown_from_high, max_drawdown, quantiles, sharpe, spearman_ic)
from ..jobs.universe import get_universe

HORIZONS_M = [1, 3, 6, 12]           # meses
TRADING = {63: "3m", 126: "6m"}      # días hábiles para distribución condicional
DD_THRESHOLD = -0.20                 # "en caída": drawdown >= 20% desde máximo de 1 año


def monthly_closes(bars: List[dict]) -> Dict[str, float]:
    """Último cierre de cada mes (clave 'YYYY-MM')."""
    out: Dict[str, float] = {}
    for b in bars:  # bars vienen ascendentes por fecha
        out[b["as_of"][:7]] = b["close"]
    return out


def momentum_12_1(mc: Dict[str, float], months: List[str], t: int) -> float | None:
    """Momentum 12-1 en el mes `months[t]`: retorno de t-12 a t-1 (omite el último mes).
    Solo usa información disponible en t (sin lookahead)."""
    if t < 12:
        return None
    p_old = mc.get(months[t - 12])
    p_recent = mc.get(months[t - 1])
    if not p_old or not p_recent or p_old <= 0:
        return None
    return p_recent / p_old - 1.0


def fwd_return_m(mc: Dict[str, float], months: List[str], t: int, h: int) -> float | None:
    if t + h >= len(months):
        return None
    p0 = mc.get(months[t]); p1 = mc.get(months[t + h])
    if not p0 or not p1 or p0 <= 0:
        return None
    return p1 / p0 - 1.0


def run_backtest(provider, tickers: List[str], acceptance: str = "MU", rng: str = "5y") -> dict:
    daily: Dict[str, List[dict]] = {}
    for t in tickers:
        bars = provider.get_history_bars(t, rng=rng)
        if len(bars) > 60:
            daily[t] = bars
    monthlies = {t: monthly_closes(b) for t, b in daily.items()}

    # eje de meses común (unión ordenada)
    all_months = sorted({m for mc in monthlies.values() for m in mc})

    # ----- Walk-forward: IC de rango por horizonte + estrategia top-quintil (h=1) -----
    ic_by_h: Dict[int, List[float]] = {h: [] for h in HORIZONS_M}
    strat_rets: List[float] = []
    bench_rets: List[float] = []

    for t in range(len(all_months)):
        # señal transversal en el mes t
        sig: Dict[str, float] = {}
        for tk, mc in monthlies.items():
            s = momentum_12_1(mc, all_months, t)
            if s is not None:
                sig[tk] = s
        if len(sig) < 8:
            continue
        # IC por horizonte (fuera de muestra: forward desde t)
        for h in HORIZONS_M:
            names = [tk for tk in sig if fwd_return_m(monthlies[tk], all_months, t, h) is not None]
            if len(names) >= 8:
                ic = spearman_ic([sig[n] for n in names], [fwd_return_m(monthlies[n], all_months, t, h) for n in names])
                if ic is not None:
                    ic_by_h[h].append(ic)
        # estrategia h=1: top quintil equiponderado vs. equiponderado del universo
        names1 = [tk for tk in sig if fwd_return_m(monthlies[tk], all_months, t, 1) is not None]
        if len(names1) >= 10:
            ranked = sorted(names1, key=lambda n: sig[n], reverse=True)
            top = ranked[: max(1, len(ranked) // 5)]
            strat = sum(fwd_return_m(monthlies[n], all_months, t, 1) for n in top) / len(top)
            bench = sum(fwd_return_m(monthlies[n], all_months, t, 1) for n in names1) / len(names1)
            strat_rets.append(strat); bench_rets.append(bench)

    def cum(rs: List[float]) -> float:
        c = 1.0
        for r in rs:
            c *= (1 + r)
        return c - 1.0

    def equity(rs: List[float]) -> List[float]:
        e = [1.0]
        for r in rs:
            e.append(e[-1] * (1 + r))
        return e

    ic_summary = {}
    for h in HORIZONS_M:
        xs = ic_by_h[h]
        ic_summary[f"{h}m"] = {
            "mean_ic": round(sum(xs) / len(xs), 4) if xs else None,
            "ic_positive_frac": round(sum(1 for x in xs if x > 0) / len(xs), 3) if xs else None,
            "months": len(xs),
        }

    strategy = {
        "months": len(strat_rets),
        "strategy_cum_return": round(cum(strat_rets), 4) if strat_rets else None,
        "benchmark_cum_return": round(cum(bench_rets), 4) if bench_rets else None,
        "excess_cum_return": round(cum(strat_rets) - cum(bench_rets), 4) if strat_rets else None,
        "strategy_sharpe": round(sharpe(strat_rets), 3) if sharpe(strat_rets) else None,
        "benchmark_sharpe": round(sharpe(bench_rets), 3) if sharpe(bench_rets) else None,
        "strategy_max_drawdown": round(max_drawdown(equity(strat_rets)), 4) if strat_rets else None,
    }

    # ----- Episodios de caída/recuperación: distribución condicional de retornos -----
    def conditional_dist(bars: List[dict]) -> dict:
        prices = [b["close"] for b in bars]
        dd = drawdown_from_high(prices, lookback=252)
        res = {}
        for days, label in TRADING.items():
            fwd = []
            for i in range(len(prices) - days):
                if dd[i] <= DD_THRESHOLD and prices[i] > 0:
                    fwd.append(prices[i + days] / prices[i] - 1.0)
            res[label] = {"n": len(fwd), **({k: (round(v, 4) if v is not None else None)
                                            for k, v in quantiles(fwd, [0.1, 0.25, 0.5, 0.75, 0.9]).items()} if fwd else {})}
        return res

    pooled_bars: List[dict] = []
    for b in daily.values():
        pooled_bars += b
    pooled_bars.sort(key=lambda x: x["as_of"])

    acceptance = acceptance.upper()
    summary = {
        "experimental": True,
        "note": "Evaluación fuera de muestra de una señal simple (momentum 12-1). NO es recomendación.",
        "universe_size": len(daily),
        "months_axis": len(all_months),
        "rank_ic_by_horizon": ic_summary,
        "strategy_vs_benchmark_h1": strategy,
        "drawdown_recovery_distribution": {
            "threshold": DD_THRESHOLD,
            "universe_pooled": conditional_dist(pooled_bars) if pooled_bars else {},
            acceptance: conditional_dist(daily[acceptance]) if acceptance in daily else "sin histórico",
        },
    }
    # MU como aceptación: señal actual y percentil transversal (mismas funciones)
    if acceptance in monthlies and all_months:
        t = len(all_months) - 1
        sigs = {tk: momentum_12_1(mc, all_months, t) for tk, mc in monthlies.items()}
        sigs = {k: v for k, v in sigs.items() if v is not None}
        if acceptance in sigs and len(sigs) > 1:
            below = sum(1 for v in sigs.values() if v < sigs[acceptance])
            summary["acceptance_case"] = {
                "ticker": acceptance,
                "momentum_12_1": round(sigs[acceptance], 4),
                "cross_sectional_percentile": round(100 * below / (len(sigs) - 1), 1),
                "interpretation": "percentil de atractivo por momentum; señal observable, no predicción.",
            }
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description="GIIC forecasting backtest (experimental)")
    p.add_argument("--acceptance", default="MU")
    p.add_argument("--range", default="5y")
    p.add_argument("--tickers", nargs="*")
    args = p.parse_args(argv)
    tickers = [t.upper() for t in args.tickers] if args.tickers else [i.ticker for i in get_universe(include_etfs=False)]
    try:
        summary = run_backtest(get_provider("yahoo"), tickers, args.acceptance, args.range)
    except Exception as e:
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:200]}, indent=2))
        return 1
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
