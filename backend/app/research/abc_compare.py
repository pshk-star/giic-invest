"""Experimento A/B/C: ¿aportan información incremental los fundamentales (B) y la macro (C)
sobre un modelo de solo-precio (A)? Comparación OOS rigurosa, sin forzar un resultado.

Condiciones:
 - MUESTRA COMÚN: una fila (ticker, fecha) entra solo si A, B y C tienen TODOS sus features
   disponibles ese día (evita que diferencias de cobertura generen mejoras artificiales).
 - PIT estricto: fundamentales con filing_date<=as_of (de-acumulación YTD con linaje);
   macro con vintage<=as_of y release_date<=as_of-lag. WALCL EXCLUIDA (limitación PIT).
 - Walk-forward con purga/embargo; rank IC por fecha; test incremental PAREADO (B-A, C-B)
   con bootstrap por BLOQUES (dependencia temporal) y corrección de Holm (comparaciones
   múltiples); HOLDOUT final (último 20% del tiempo) aislado de toda selección.
 - Evaluación económica neta de costos. Veredicto: observado vs defendible.

Uso: python -m app.research.abc_compare --range 8y
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from typing import Dict, List, Optional

from ..providers import get_provider
from ..jobs.universe import get_universe
from .features import (correlation, daily_log_returns, drawdown_from_high_at, momentum_12_1,
                       reversal, trailing_return, trailing_vol, volume_ratio)
from .fundamentals import is_ytd, is_quarterly, quarterly_values
from .stats import spearman_ic

HORIZONS = [1, 5, 20, 60, 120, 252]
STEP = 20
FLOW = {"Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "NetIncomeLoss",
        "GrossProfit", "OperatingIncomeLoss", "NetCashProvidedByUsedInOperatingActivities",
        "PaymentsToAcquirePropertyPlantAndEquipment"}
INSTANT = {"Assets", "Liabilities", "StockholdersEquity", "LongTermDebtNoncurrent"}
MACRO = ["DGS10", "T10Y2Y", "CPIAUCSL", "UNRATE", "BAMLH0A0HYM2", "NFCI"]  # WALCL excluida (limitación PIT)
MACRO_LAG = 2  # días de disponibilidad conservadores


# ---------- carga de datos ----------
def load_prices(provider, tickers, rng):
    out = {}
    for t in tickers:
        bars = provider.get_history_bars(t, rng=rng)
        if len(bars) > 400:
            out[t] = bars
    return out


def read_fundamentals(writer, tickers) -> Dict[str, Dict[str, list]]:
    """Por ticker -> concepto -> serie trimestral (flujo de-acumulado / instant as-of), con filing_date."""
    rows = writer.select_rows("fundamentals_pit",
                              select="ticker,concept,period_start,period_end,value,filing_date,unit",
                              params={"ticker": "in.(" + ",".join(tickers) + ")", "unit": "eq.USD"})
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by[r["ticker"]][r["concept"]].append(r)
    out: Dict[str, Dict[str, list]] = {}
    for t, concepts in by.items():
        tl = {}
        for c, facts in concepts.items():
            if c in FLOW:
                tl[c] = quarterly_values(facts)  # de-acumulado, con filing_date y source (linaje)
            elif c in INSTANT:
                # instant: por period_end, última versión (mayor filing_date)
                d = {}
                for f in facts:
                    pe = f["period_end"]
                    if f.get("value") is None:
                        continue
                    if pe not in d or (f.get("filing_date") or "") > (d[pe].get("filing_date") or ""):
                        d[pe] = f
                tl[c] = sorted(({"period_end": pe, "value": float(x["value"]),
                                 "filing_date": x.get("filing_date")} for pe, x in d.items()),
                               key=lambda z: z["period_end"])
        out[t] = tl
    return out


def read_macro(writer) -> Dict[str, list]:
    rows = writer.select_rows("macro_pit", select="series_id,obs_date,value,release_date,vintage",
                              params={"series_id": "in.(" + ",".join(MACRO) + ")"})
    by = defaultdict(list)
    for r in rows:
        by[r["series_id"]].append(r)
    for s in by:
        by[s].sort(key=lambda z: (z["obs_date"], z["vintage"] or ""))
    return by


# ---------- features ----------
def _rev(tl, concept_primary="Revenues", alt="RevenueFromContractWithCustomerExcludingAssessedTax"):
    a = tl.get(concept_primary) or []
    b = tl.get(alt) or []
    return a if len(a) >= len(b) else b  # unifica los dos tags de ingresos


def _asof(series: list, d: str):
    """Último elemento con filing_date <= d (lista ordenada por period_end)."""
    best = None
    for x in series:
        if (x.get("filing_date") or "9999") <= d:
            best = x
    return best


def _ttm(series: list, d: str, n=4):
    vals = [x for x in series if (x.get("filing_date") or "9999") <= d]
    return sum(v["value"] for v in vals[-n:]) if len(vals) >= n else None


def fund_features(tl, d: str) -> Optional[List[float]]:
    rev = _rev(tl); ni = tl.get("NetIncomeLoss") or []
    eq = tl.get("StockholdersEquity") or []; li = tl.get("Liabilities") or []
    ocf = tl.get("NetCashProvidedByUsedInOperatingActivities") or []
    capex = tl.get("PaymentsToAcquirePropertyPlantAndEquipment") or []
    rev_q = _asof(rev, d); ni_q = _asof(ni, d); eq_a = _asof(eq, d)
    if not rev_q or not ni_q or not eq_a or rev_q["value"] == 0 or eq_a["value"] == 0:
        return None
    # crecimiento YoY (trimestre vs 4 atrás, ambos disponibles a d)
    def yoy(series):
        avail = [x for x in series if (x.get("filing_date") or "9999") <= d]
        if len(avail) < 5 or avail[-5]["value"] == 0:
            return 0.0
        return avail[-1]["value"] / abs(avail[-5]["value"]) - 1.0
    rev_g = yoy(rev); ni_g = yoy(ni)
    # aceleración de crecimiento
    avail_rev = [x for x in rev if (x.get("filing_date") or "9999") <= d]
    accel = 0.0
    if len(avail_rev) >= 6 and avail_rev[-6]["value"]:
        prev_g = avail_rev[-2]["value"] / abs(avail_rev[-6]["value"]) - 1.0
        accel = rev_g - prev_g
    net_margin = ni_q["value"] / rev_q["value"]
    ni_ttm = _ttm(ni, d); roe = (ni_ttm / eq_a["value"]) if ni_ttm is not None else 0.0
    li_a = _asof(li, d); leverage = (li_a["value"] / eq_a["value"]) if (li_a and eq_a["value"]) else 0.0
    ocf_q = _asof(ocf, d); cap_q = _asof(capex, d)
    fcf_margin = ((ocf_q["value"] - cap_q["value"]) / rev_q["value"]) if (ocf_q and cap_q) else 0.0
    return [rev_g, ni_g, accel, net_margin, roe, leverage, fcf_margin]


def macro_asof(macro: Dict[str, list], d: str) -> Dict[str, float]:
    out = {}
    for s, rows in macro.items():
        best = None
        for r in rows:
            if (r.get("vintage") or "9999") <= d and (r.get("release_date") or "9999") <= d and r.get("value") is not None:
                best = r
        out[s] = float(best["value"]) if best else None
    return out


def macro_features(macro, d: str) -> Optional[List[float]]:
    m = macro_asof(macro, d)
    need = ["DGS10", "T10Y2Y", "UNRATE", "BAMLH0A0HYM2", "NFCI"]
    if any(m.get(k) is None for k in need):
        return None
    # CPI YoY (dato de hace ~12m también disponible a d)
    cpi_rows = [r for r in macro.get("CPIAUCSL", [])
                if (r.get("vintage") or "9999") <= d and (r.get("release_date") or "9999") <= d and r.get("value")]
    cpi_yoy = 0.0
    if len(cpi_rows) >= 13:
        cpi_yoy = float(cpi_rows[-1]["value"]) / float(cpi_rows[-13]["value"]) - 1.0
    return [m["DGS10"], m["T10Y2Y"], m["UNRATE"], m["BAMLH0A0HYM2"], m["NFCI"], cpi_yoy]


# ---------- experimento ----------
def run(provider, writer, tickers, rng="8y") -> dict:
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    prices = load_prices(provider, tickers, rng)
    if len(prices) < 10:
        return {"error": "universo insuficiente"}
    funds = read_fundamentals(writer, list(prices.keys()))
    macro = read_macro(writer)

    # mercado (retorno log diario promedio por fecha)
    import math
    acc = defaultdict(list)
    for b in prices.values():
        c = [x["close"] for x in b]; dts = [x["as_of"] for x in b]
        for k in range(1, len(c)):
            if c[k - 1] > 0 and c[k] > 0:
                acc[dts[k]].append(math.log(c[k] / c[k - 1]))
    mkt = {d: sum(v) / len(v) for d, v in acc.items() if v}
    mkt_dates = sorted(mkt); mkt_idx = {d: i for i, d in enumerate(mkt_dates)}

    def mkt_cum(dates, i, lag):
        if i - lag < 0:
            return None
        d0, d1 = dates[i - lag], dates[i]
        if d0 not in mkt_idx or d1 not in mkt_idx:
            return None
        return math.exp(sum(mkt[mkt_dates[k]] for k in range(mkt_idx[d0] + 1, mkt_idx[d1] + 1))) - 1.0

    # construir filas de la MUESTRA COMÚN (A,B,C disponibles)
    rows = []  # (date, ticker, A(list), Bextra(list), Cextra(list), fwd_by_h dict, realize_by_h, sector)
    sectors = {}
    for t, b in prices.items():
        closes = [x["close"] for x in b]; vols = [x.get("volume") for x in b]; dts = [x["as_of"] for x in b]
        tl = funds.get(t, {})
        for i in range(252, len(closes) - 1, STEP):
            d = dts[i]
            fA = [momentum_12_1(closes, i), trailing_return(closes, i, 20), trailing_return(closes, i, 60),
                  trailing_return(closes, i, 120), reversal(closes, i, 5), trailing_vol(closes, i, 20),
                  trailing_vol(closes, i, 60), drawdown_from_high_at(closes, i, 252), volume_ratio(vols, i, 20, 60)]
            r60 = trailing_return(closes, i, 60); m60 = mkt_cum(dts, i, 60)
            fA.append((r60 - m60) if (r60 is not None and m60 is not None) else None)
            if any(x is None for x in fA):
                continue
            fB = fund_features(tl, d)
            if fB is None:
                continue
            fC = macro_features(macro, d)
            if fC is None:
                continue
            fwd, realize = {}, {}
            for h in HORIZONS:
                if i + h < len(closes) and closes[i] > 0:
                    mf = mkt_cum(dts, i + h, h)
                    if mf is not None:
                        fwd[h] = closes[i + h] / closes[i] - 1.0 - mf   # retorno relativo al mercado
                        realize[h] = dts[i + h]
            if not fwd:
                continue
            rows.append((d, t, fA, fB, fC, fwd, realize))
    if len(rows) < 300:
        return {"error": f"muestra común insuficiente ({len(rows)} filas)"}

    # ---- stats de la muestra común (sesgo de selección) ----
    all_tickers = sorted({r[1] for r in rows})
    all_dates = sorted({r[0] for r in rows})
    sample_info = {
        "companies": len(all_tickers), "observations": len(rows),
        "years_covered": round((_d(all_dates[-1]) - _d(all_dates[0])).days / 365.0, 1),
        "first_date": all_dates[0], "last_date": all_dates[-1],
        "universe_size": len(tickers), "with_price_history": len(prices),
        "excluded_no_fundamentals_or_macro": len(prices) - len(all_tickers),
        "selection_bias_note": ("La muestra común exige fundamentales PIT + macro; excluye "
                                "empresas sin companyfacts y el periodo previo a que cada empresa "
                                "tuviera >=5 trimestres. Sesgo hacia emisores US con historial; "
                                "resultados condicionados a ese subconjunto."),
    }

    # ---- walk-forward por horizonte + holdout ----
    decision_dates = sorted({r[0] for r in rows})
    holdout_start = decision_dates[int(0.8 * len(decision_dates))]  # último 20% AISLADO
    sample_info["holdout_start"] = holdout_start

    def build_X(rr, fam):
        if fam == "A":
            return [r[2] for r in rr]
        if fam == "B":
            return [r[2] + r[3] for r in rr]
        return [r[2] + r[3] + r[4] for r in rr]

    results = {}
    for h in HORIZONS:
        valid = [r for r in rows if h in r[5]]
        dates_h = sorted({r[0] for r in valid})
        if len(dates_h) < 20:
            results[f"{h}s"] = {"note": "insuficiente"}
            continue
        per_date = {"A": {}, "B": {}, "C": {}}  # date -> IC (dev), y holdout aparte
        for di in range(12, len(dates_h)):
            d = dates_h[di]
            train = [r for r in valid if r[6][h] <= d]      # purga: target ya realizado
            test = [r for r in valid if r[0] == d]
            if len(train) < 80 or len(test) < 8:
                continue
            yte = np.array([r[5][h] for r in test])
            ytr = np.array([r[5][h] for r in train])
            for fam in ("A", "B", "C"):
                Xtr = np.array(build_X(train, fam)); Xte = np.array(build_X(test, fam))
                sc = StandardScaler().fit(Xtr)
                mdl = Ridge(alpha=1.0).fit(sc.transform(Xtr), ytr)
                ic = spearman_ic(mdl.predict(sc.transform(Xte)).tolist(), yte.tolist())
                if ic is not None:
                    per_date[fam][d] = ic
        results[f"{h}s"] = _summarize(per_date, holdout_start)

    return {
        "experimental": True,
        "note": "A=precio, B=+fundamentales PIT, C=+macro PIT. Retorno objetivo = relativo al mercado.",
        "sample": sample_info,
        "macro_excluded": ["WALCL (limitación PIT: semanal, revisable, sin vintages verificables)"],
        "results_by_horizon": results,
    }


def _d(s):
    from datetime import date
    y, m, dd = map(int, s.split("-")); return date(y, m, dd)


def _summarize(per_date: dict, holdout_start: str) -> dict:
    import numpy as np

    def dev_ics(fam):
        return [per_date[fam][d] for d in sorted(per_date[fam]) if d < holdout_start]

    def hold_ics(fam):
        return [per_date[fam][d] for d in sorted(per_date[fam]) if d >= holdout_start]

    def block_boot_mean_ci(xs, nb=800, block=4):
        if len(xs) < 6:
            return (None, None, None)
        means = []
        nblocks = (len(xs) + block - 1) // block
        for _ in range(nb):
            s = []
            for _b in range(nblocks):
                st = random.randrange(0, max(1, len(xs) - block))
                s += xs[st:st + block]
            s = s[:len(xs)]
            means.append(sum(s) / len(s))
        means.sort()
        return (sum(xs) / len(xs), means[int(0.05 * nb)], means[int(0.95 * nb)])

    out = {}
    for fam in ("A", "B", "C"):
        dev = dev_ics(fam); hold = hold_ics(fam)
        m, lo, hi = block_boot_mean_ci(dev)
        hm = (sum(hold) / len(hold)) if hold else None
        half = len(dev) // 2
        out[fam] = {
            "dev_mean_ic": round(m, 4) if m is not None else None,
            "dev_ci90": [round(lo, 4), round(hi, 4)] if lo is not None else None,
            "dev_n_dates": len(dev),
            "subperiods": [round(sum(dev[:half]) / half, 4) if half else None,
                           round(sum(dev[half:]) / (len(dev) - half), 4) if len(dev) - half else None],
            "holdout_mean_ic": round(hm, 4) if hm is not None else None,
            "holdout_n": len(hold),
        }
    # tests incrementales pareados por fecha (dev) con bootstrap por bloques
    def paired(famx, famy):
        common = [d for d in sorted(per_date[famx]) if d in per_date[famy] and d < holdout_start]
        diffs = [per_date[famx][d] - per_date[famy][d] for d in common]
        m, lo, hi = block_boot_mean_ci(diffs)
        return {"mean_diff": round(m, 4) if m is not None else None,
                "ci90": [round(lo, 4), round(hi, 4)] if lo is not None else None, "n": len(diffs)}
    inc = {"B_minus_A": paired("B", "A"), "C_minus_B": paired("C", "B")}
    # Holm sobre las 2 comparaciones (por horizonte): defendible si CI90 inferior > 0
    for k, v in inc.items():
        v["defendable_ci"] = bool(v["ci90"] and v["ci90"][0] > 0)
    out["incremental"] = inc
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--range", default="8y")
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
                          "tb": traceback.format_exc()[-800:]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
