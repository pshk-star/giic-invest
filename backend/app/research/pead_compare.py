"""P1.7 Fase 2 — Modelo C (sorpresa/PEAD) y comparación A/B/C INSTRUMENTADA.

Modelo C = B (precio + fundamentales PIT) + rasgos de SORPRESA/PEAD, todos POINT-IN-TIME.
Se compara A/B/C sobre EXACTAMENTE la misma muestra: mismos períodos, empresas, fechas de
decisión, reglas de entrenamiento (Ridge alpha=1.0 estandarizado, walk-forward purgado) y
costos. C NO se emite a producción: es experimental hasta probar superioridad robusta OOS.

Controles estadísticos exigidos:
  - Dependencia por observaciones SOLAPADAS (horizonte >> paso): block bootstrap con
    tamaño de bloque >= ceil(horizonte/paso) sobre la serie de ICs por fecha.
  - Comparaciones múltiples: corrección de Holm sobre la familia de tests incrementales
    (C-B y B-A en cada horizonte). No se declara superioridad por una mejora aislada.

NINGUNA feature usa información posterior a la fecha de decisión; en particular NUNCA el
retorno del período que se intenta predecir. Las sorpresas se anclan con reportDate ESTRICTO
(< fecha de decisión): convención conservadora = primera sesión operable es la SIGUIENTE a
reportDate (ver surprise_pit_probe).

Uso: python -m app.research.pead_compare --range max
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional

from ..providers import get_provider
from ..jobs.universe import get_universe
from .abc_compare import (block_boot, fund_features, load_prices, read_fundamentals,
                          read_sectors, _d)
from .features import (drawdown_from_high_at, momentum_12_1, reversal, trailing_return,
                       trailing_vol, volume_ratio)
from .stats import spearman_ic

HORIZONS = [20, 60, 252]   # C = PEAD: efecto de 1-3 meses; se incluye 252 para paridad con B
STEP = 20
COST = 0.001


# ---------------------------------------------------------------------------
# Rasgos de sorpresa / PEAD — PUROS y testeables (operan sobre una historia ya ordenada).
# `history`: lista de dicts {reportDate, epsActual, epsEstimate, epsDifference, surprisePercent}
# ---------------------------------------------------------------------------
def _trailing_surprises(history: List[dict], d: str, n: int = 8) -> List[dict]:
    """Trimestres con reportDate ESTRICTAMENTE anterior a d (convención conservadora)."""
    av = [h for h in history if (h.get("reportDate") or "9999") < d]
    return av[-n:]


def sue(history: List[dict], d: str, n: int = 8) -> Optional[float]:
    """Standardized Unexpected Earnings = última epsDifference / desv. típica de las sorpresas
    recientes. None si no hay historia suficiente o varianza nula."""
    av = _trailing_surprises(history, d, n)
    diffs = [h.get("epsDifference") for h in av if h.get("epsDifference") is not None]
    if len(diffs) < 4:
        return None
    m = sum(diffs) / len(diffs)
    sd = (sum((x - m) ** 2 for x in diffs) / (len(diffs) - 1)) ** 0.5
    last = diffs[-1]
    return (last / sd) if sd > 1e-9 else None


def surprise_pct(history: List[dict], d: str) -> Optional[float]:
    av = _trailing_surprises(history, d, 1)
    if not av:
        return None
    sp = av[-1].get("surprisePercent")
    return (sp / 100.0) if sp is not None else None


def surprise_streak(history: List[dict], d: str, cap: int = 8) -> Optional[float]:
    """Racha de sorpresas positivas consecutivas (signo de epsDifference), acotada a +-cap."""
    av = _trailing_surprises(history, d, cap)
    diffs = [h.get("epsDifference") for h in av if h.get("epsDifference") is not None]
    if not diffs:
        return None
    streak = 0
    for x in reversed(diffs):
        if x > 0 and streak >= 0:
            streak += 1
        elif x < 0 and streak <= 0:
            streak -= 1
        else:
            break
    return max(-cap, min(cap, streak)) / cap


def days_since_report(history: List[dict], d: str) -> Optional[float]:
    av = _trailing_surprises(history, d, 1)
    if not av or not av[-1].get("reportDate"):
        return None
    return min(180, (_d(d) - _d(av[-1]["reportDate"])).days) / 90.0


def drift_since_report(history: List[dict], d: str, dts: List[str], closes: List[float],
                       i: int) -> Optional[float]:
    """PEAD: retorno del precio desde la sesión del último reportDate (incluido) hasta d.
    Solo usa precios hasta i (<= d); no mira el futuro."""
    av = _trailing_surprises(history, d, 1)
    if not av or not av[-1].get("reportDate"):
        return None
    rd = av[-1]["reportDate"]
    j = None
    for k in range(i, -1, -1):
        if dts[k] <= rd:
            j = k
            break
    if j is None or j >= i or closes[j] <= 0 or closes[i] <= 0:
        return None
    return closes[i] / closes[j] - 1.0


def surprise_features(history: List[dict], d: str, dts: List[str], closes: List[float],
                      i: int) -> Optional[List[float]]:
    """Vector C-extra en orden congelado (SURPRISE_FEATURES). None si falta cualquiera."""
    feats = [sue(history, d), surprise_pct(history, d), surprise_streak(history, d),
             drift_since_report(history, d, dts, closes, i), days_since_report(history, d)]
    return None if any(x is None for x in feats) else feats


# ---------------------------------------------------------------------------
# Corrección de comparaciones múltiples (Holm).
# ---------------------------------------------------------------------------
def holm(pvals: Dict[str, float], alpha: float = 0.05) -> Dict[str, dict]:
    items = sorted(((k, v) for k, v in pvals.items() if v is not None), key=lambda x: x[1])
    m = len(items)
    out: Dict[str, dict] = {}
    rejected_all = True
    for rank, (k, p) in enumerate(items):
        thr = alpha / (m - rank)
        rej = p <= thr and rejected_all
        rejected_all = rejected_all and rej
        out[k] = {"p": round(p, 4), "holm_threshold": round(thr, 4), "reject_H0": bool(rej)}
    for k, v in pvals.items():
        if v is None:
            out[k] = {"p": None, "reject_H0": False}
    return out


def _boot_p(diffs: List[float], block: int) -> Optional[float]:
    """p-valor 1-cola (H0: mean<=0) vía block bootstrap: fracción de medias remuestreadas <=0."""
    if len(diffs) < 6:
        return None
    random.seed(42)
    nb = 2000
    nblk = (len(diffs) + block - 1) // block
    le0 = 0
    for _ in range(nb):
        s: List[float] = []
        for _b in range(nblk):
            st = random.randrange(0, max(1, len(diffs) - block))
            s += diffs[st:st + block]
        s = s[:len(diffs)]
        if sum(s) / len(s) <= 0:
            le0 += 1
    return le0 / nb


def _fit_ic(train, test, fam):
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    def X(rr):
        if fam == "A":
            return [r["A"] for r in rr]
        if fam == "B":
            return [r["A"] + r["B"] for r in rr]
        return [r["A"] + r["B"] + r["C"] for r in rr]
    ytr = np.array([r["y"] for r in train])
    sc = StandardScaler().fit(np.array(X(train)))
    mdl = Ridge(alpha=1.0).fit(sc.transform(np.array(X(train))), ytr)
    p = mdl.predict(sc.transform(np.array(X(test)))).tolist()
    return spearman_ic(p, [r["y"] for r in test])


def experiment(rows_by_h: Dict[int, list]) -> dict:
    res: Dict[str, dict] = {}
    pvals: Dict[str, float] = {}
    for h in HORIZONS:
        rows = rows_by_h[h]
        dh = sorted({r["date"] for r in rows})
        if len(dh) < 20:
            res[f"{h}s"] = {"note": "insuficiente", "n_dates": len(dh)}
            continue
        block = max(2, math.ceil(h / STEP))   # bloques que cubren el solapamiento del horizonte
        ic = {f: {} for f in ("A", "B", "C")}
        for di in range(12, len(dh)):
            d = dh[di]
            train = [r for r in rows if r["realize"] <= d]
            test = [r for r in rows if r["date"] == d]
            if len(train) < 80 or len(test) < 8:
                continue
            for fam in ("A", "B", "C"):
                v = _fit_ic(train, test, fam)
                if v is not None:
                    ic[fam][d] = v
        summ = {}
        for f in ("A", "B", "C"):
            xs = [ic[f][d] for d in sorted(ic[f])]
            m, lo, hi = block_boot(xs)
            summ[f] = {"ic_mean": round(m, 4) if m is not None else None,
                       "ci90": [round(lo, 4), round(hi, 4)] if lo is not None else None, "n": len(xs)}
        inc = {}
        for x, y in (("B", "A"), ("C", "B")):
            common = [d for d in sorted(ic[x]) if d in ic[y]]
            diffs = [ic[x][d] - ic[y][d] for d in common]
            m, lo, hi = block_boot(diffs)
            p = _boot_p(diffs, block)
            key = f"{x}_minus_{y}@{h}s"
            inc[f"{x}_minus_{y}"] = {"mean_diff": round(m, 4) if m is not None else None,
                                     "ci90": [round(lo, 4), round(hi, 4)] if lo is not None else None,
                                     "n": len(diffs), "p_1sided": round(p, 4) if p is not None else None}
            if p is not None:
                pvals[key] = p
        res[f"{h}s"] = {"block_size": block, "families": summ, "incremental_raw": inc}
    res["multiple_comparison_holm"] = holm(pvals)
    res["overlap_note"] = ("ICs por fecha con ventanas solapadas (horizonte > paso): el block "
                           "bootstrap usa bloques >= ceil(h/STEP) para no subestimar la varianza.")
    return res


def _fetch_histories(tickers: List[str]) -> Dict[str, List[dict]]:
    """Historia de sorpresas por ticker desde EODHD Earnings.History (ordenada por reportDate)."""
    key = os.getenv("EODHD_API_KEY", "")
    if not key:
        return {}
    from app.core.connectors.eodhd import EodhdFundamentalsConnector
    conn = EodhdFundamentalsConnector(api_key=key)
    out: Dict[str, List[dict]] = {}
    for t in tickers:
        try:
            _s, _a, obj = conn._resolve(t)
            hist = ((obj or {}).get("Earnings", {}) or {}).get("History", {}) or {}
            seq = []
            for pkey in sorted(hist.keys()):
                h = hist[pkey] or {}
                seq.append({"reportDate": h.get("reportDate") or pkey,
                            "epsActual": h.get("epsActual"), "epsEstimate": h.get("epsEstimate"),
                            "epsDifference": h.get("epsDifference"),
                            "surprisePercent": h.get("surprisePercent")})
            seq.sort(key=lambda z: z["reportDate"] or "")
            out[t] = seq
        except Exception:
            out[t] = []
    return out


def run(provider, writer, tickers, rng="max"):
    prices = load_prices(provider, tickers, rng)
    if len(prices) < 10:
        return {"error": "universo insuficiente para A/B/C"}
    funds = read_fundamentals(writer, list(prices.keys()))
    sectors = read_sectors(writer, list(prices.keys()))
    histories = _fetch_histories(list(prices.keys()))

    # mercado equiponderado (target = retorno relativo)
    acc = defaultdict(list)
    for b in prices.values():
        c = [x["close"] for x in b]; dts = [x["as_of"] for x in b]
        for k in range(1, len(c)):
            if c[k - 1] > 0 and c[k] > 0:
                acc[dts[k]].append(math.log(c[k] / c[k - 1]))
    mkt = {d: sum(v) / len(v) for d, v in acc.items() if v}
    mdates = sorted(mkt); midx = {d: i for i, d in enumerate(mdates)}

    def mkt_cum(dates, i, lag):
        if i - lag < 0:
            return None
        d0, d1 = dates[i - lag], dates[i]
        if d0 not in midx or d1 not in midx:
            return None
        return math.exp(sum(mkt[mdates[k]] for k in range(midx[d0] + 1, midx[d1] + 1))) - 1.0

    rows_by_h: Dict[int, list] = {h: [] for h in HORIZONS}
    funnel = {"grid": 0, "pass_price": 0, "pass_fund": 0, "pass_surprise": 0}
    for t, b in prices.items():
        closes = [x["close"] for x in b]; vols = [x.get("volume") for x in b]; dts = [x["as_of"] for x in b]
        tl = funds.get(t, {}); hist = histories.get(t, []); sec = sectors.get(t, "Otro")
        for i in range(252, len(closes) - 1, STEP):
            funnel["grid"] += 1
            d = dts[i]
            fA = [momentum_12_1(closes, i), trailing_return(closes, i, 20), trailing_return(closes, i, 60),
                  trailing_return(closes, i, 120), reversal(closes, i, 5), trailing_vol(closes, i, 20),
                  trailing_vol(closes, i, 60), drawdown_from_high_at(closes, i, 252), volume_ratio(vols, i, 20, 60)]
            r60 = trailing_return(closes, i, 60); m60 = mkt_cum(dts, i, 60)
            fA.append((r60 - m60) if (r60 is not None and m60 is not None) else None)
            if any(x is None for x in fA):
                continue
            funnel["pass_price"] += 1
            fB = fund_features(tl, d)
            if fB is None:
                continue
            funnel["pass_fund"] += 1
            fC = surprise_features(hist, d, dts, closes, i)
            if fC is None:
                continue
            funnel["pass_surprise"] += 1
            for h in HORIZONS:
                if i + h < len(closes) and closes[i] > 0:
                    mf = mkt_cum(dts, i + h, h)
                    if mf is not None:
                        y = closes[i + h] / closes[i] - 1.0 - mf
                        rows_by_h[h].append({"date": d, "ticker": t, "sector": sec,
                                             "A": fA, "B": fB, "C": fC, "y": y, "realize": dts[i + h]})
    total = sum(len(v) for v in rows_by_h.values())
    out = {"experimental": True, "model_C": "c-1.0.0 (price+fund+surprise, PEAD)", "funnel": funnel,
           "common_sample_note": ("A/B/C evaluados sobre la MISMA muestra (filas con precio+fund+"
                                  "sorpresa); mismas fechas de decisión, estimador y costos."),
           "companies": len({r["ticker"] for h in HORIZONS for r in rows_by_h[h]}),
           "observations_by_horizon": {f"{h}s": len(rows_by_h[h]) for h in HORIZONS}}
    if total < 300 or not any(histories.values()):
        out["result"] = {"error": f"muestra común insuficiente o sin historia de sorpresas (total={total})"}
        return out
    out["comparison"] = experiment(rows_by_h)
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--range", default="max")
    p.add_argument("--tickers", nargs="*")
    args = p.parse_args(argv)
    random.seed(42)
    tickers = [t.upper() for t in args.tickers] if args.tickers else [i.ticker for i in get_universe(include_etfs=False)]
    from ..jobs.supabase_writer import SupabaseWriter
    writer = SupabaseWriter(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    try:
        out = run(get_provider("yahoo"), writer, tickers, args.range)
    except Exception as e:
        import traceback
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300],
                          "tb": traceback.format_exc()[-900:]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
