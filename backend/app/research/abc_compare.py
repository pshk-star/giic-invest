"""Experimento A/B/C instrumentado: diagnostica la pérdida de historia (funnel por filtro)
y corre DOS experimentos separados con la MÁXIMA historia PIT válida de cada uno:
  - AB : muestra común precio + fundamentales (sin exigir macro) -> historia más larga.
  - ABC: muestra común triple (precio + fundamentales + macro).
Comparaciones pareadas DENTRO de cada experimento (no se mezclan muestras distintas).

PIT estricto: fundamentales filing_date<=as_of (de-acumulación YTD con linaje); macro
vintage<=as_of y release_date<=as_of; WALCL excluida (limitación PIT).

Nota de validación: el 'oos_period' (último 20%) YA fue consultado en la corrida anterior;
aquí se reporta como OOS histórico, NO como holdout virgen. La validación verdaderamente
prospectiva es la emisión diaria (track record), no este periodo.

Incluye evaluación ECONÓMICA (h=20): retorno neto de costos, turnover, exposición
sectorial, drawdown, vs benchmark equiponderado.

Uso: python -m app.research.abc_compare --range max
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import defaultdict
from typing import Dict, List, Optional

from ..providers import get_provider
from ..jobs.universe import get_universe
from .features import (drawdown_from_high_at, momentum_12_1, reversal, trailing_return,
                       trailing_vol, volume_ratio)
from .fundamentals import is_quarterly, is_ytd, quarterly_values
from .stats import spearman_ic

HORIZONS = [1, 5, 20, 60, 120, 252]
STEP = 20
COST = 0.001
FLOW = {"Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "NetIncomeLoss",
        "GrossProfit", "OperatingIncomeLoss", "NetCashProvidedByUsedInOperatingActivities",
        "PaymentsToAcquirePropertyPlantAndEquipment"}
INSTANT = {"Assets", "Liabilities", "StockholdersEquity", "LongTermDebtNoncurrent"}
MACRO = ["DGS10", "T10Y2Y", "CPIAUCSL", "UNRATE", "BAMLH0A0HYM2", "NFCI"]


def _d(s):
    from datetime import date
    y, m, dd = map(int, s.split("-")); return date(y, m, dd)


def load_prices(provider, tickers, rng):
    out = {}
    for t in tickers:
        bars = provider.get_history_bars(t, rng=rng)
        if len(bars) > 400:
            out[t] = bars
    return out


def read_fundamentals(writer, tickers):
    rows = writer.select_rows("fundamentals_pit",
                              select="ticker,concept,period_start,period_end,value,filing_date,unit",
                              params={"ticker": "in.(" + ",".join(tickers) + ")", "unit": "eq.USD"})
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by[r["ticker"]][r["concept"]].append(r)
    out = {}
    for t, concepts in by.items():
        tl = {}
        for c, facts in concepts.items():
            if c in FLOW:
                tl[c] = quarterly_values(facts)
            elif c in INSTANT:
                d = {}
                for f in facts:
                    pe = f["period_end"]
                    if f.get("value") is None:
                        continue
                    if pe not in d or (f.get("filing_date") or "") > (d[pe].get("filing_date") or ""):
                        d[pe] = f
                tl[c] = sorted(({"period_end": pe, "value": float(x["value"]), "filing_date": x.get("filing_date")}
                                for pe, x in d.items()), key=lambda z: z["period_end"])
        out[t] = tl
    return out


def read_macro(writer):
    rows = writer.select_rows("macro_pit", select="series_id,obs_date,value,release_date,vintage",
                              params={"series_id": "in.(" + ",".join(MACRO) + ")"})
    by = defaultdict(list)
    for r in rows:
        by[r["series_id"]].append(r)
    for s in by:
        by[s].sort(key=lambda z: (z["obs_date"], z["vintage"] or ""))
    # rango real de disponibilidad por serie (diagnóstico)
    span = {s: {"first_vintage": (rws[0]["vintage"] if rws else None),
                "first_obs": (rws[0]["obs_date"] if rws else None), "rows": len(rws)}
            for s, rws in by.items()}
    return by, span


def read_sectors(writer, tickers):
    try:
        rows = writer.select_rows("instruments", select="ticker,sector",
                                  params={"ticker": "in.(" + ",".join(tickers) + ")"})
        return {r["ticker"]: (r.get("sector") or "Otro") for r in rows}
    except Exception:
        return {}


def _asof(series, d):
    best = None
    for x in series:
        if (x.get("filing_date") or "9999") <= d:
            best = x
    return best


def _ttm(series, d, n=4):
    vals = [x for x in series if (x.get("filing_date") or "9999") <= d]
    return sum(v["value"] for v in vals[-n:]) if len(vals) >= n else None


def fund_features(tl, d):
    rev_a = tl.get("Revenues") or []
    rev_b = tl.get("RevenueFromContractWithCustomerExcludingAssessedTax") or []
    rev = rev_a if len(rev_a) >= len(rev_b) else rev_b
    ni = tl.get("NetIncomeLoss") or []; eq = tl.get("StockholdersEquity") or []
    li = tl.get("Liabilities") or []; ocf = tl.get("NetCashProvidedByUsedInOperatingActivities") or []
    capex = tl.get("PaymentsToAcquirePropertyPlantAndEquipment") or []
    rev_q = _asof(rev, d); ni_q = _asof(ni, d); eq_a = _asof(eq, d)
    if not rev_q or not ni_q or not eq_a or rev_q["value"] == 0 or eq_a["value"] == 0:
        return None

    def yoy(series):
        av = [x for x in series if (x.get("filing_date") or "9999") <= d]
        if len(av) < 5 or av[-5]["value"] == 0:
            return 0.0
        return av[-1]["value"] / abs(av[-5]["value"]) - 1.0
    rev_g, ni_g = yoy(rev), yoy(ni)
    av_rev = [x for x in rev if (x.get("filing_date") or "9999") <= d]
    accel = 0.0
    if len(av_rev) >= 6 and av_rev[-6]["value"]:
        accel = rev_g - (av_rev[-2]["value"] / abs(av_rev[-6]["value"]) - 1.0)
    net_margin = ni_q["value"] / rev_q["value"]
    ni_ttm = _ttm(ni, d); roe = (ni_ttm / eq_a["value"]) if ni_ttm is not None else 0.0
    li_a = _asof(li, d); leverage = (li_a["value"] / eq_a["value"]) if li_a else 0.0
    ocf_q = _asof(ocf, d); cap_q = _asof(capex, d)
    fcf_margin = ((ocf_q["value"] - cap_q["value"]) / rev_q["value"]) if (ocf_q and cap_q) else 0.0
    return [rev_g, ni_g, accel, net_margin, roe, leverage, fcf_margin]


def macro_features(macro, d):
    def level(s):
        best = None
        for r in macro.get(s, []):
            if (r.get("vintage") or "9999") <= d and (r.get("release_date") or "9999") <= d and r.get("value") is not None:
                best = r
        return float(best["value"]) if best else None
    need = {s: level(s) for s in ["DGS10", "T10Y2Y", "UNRATE", "BAMLH0A0HYM2", "NFCI"]}
    if any(v is None for v in need.values()):
        return None
    cpi = [r for r in macro.get("CPIAUCSL", [])
           if (r.get("vintage") or "9999") <= d and (r.get("release_date") or "9999") <= d and r.get("value")]
    cpi_yoy = (float(cpi[-1]["value"]) / float(cpi[-13]["value"]) - 1.0) if len(cpi) >= 13 else 0.0
    return [need["DGS10"], need["T10Y2Y"], need["UNRATE"], need["BAMLH0A0HYM2"], need["NFCI"], cpi_yoy]


def block_boot(xs, nb=800, block=4):
    if len(xs) < 6:
        return (None, None, None)
    means = []
    nblk = (len(xs) + block - 1) // block
    for _ in range(nb):
        s = []
        for _b in range(nblk):
            st = random.randrange(0, max(1, len(xs) - block))
            s += xs[st:st + block]
        s = s[:len(xs)]
        means.append(sum(s) / len(s))
    means.sort()
    return (sum(xs) / len(xs), means[int(0.05 * nb)], means[int(0.95 * nb)])


def experiment(rows, families, label):
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    dec_dates = sorted({r["date"] for r in rows})
    oos_start = dec_dates[int(0.8 * len(dec_dates))] if len(dec_dates) > 5 else dec_dates[-1]

    def X(rr, fam):
        if fam == "A":
            return [r["A"] for r in rr]
        if fam == "B":
            return [r["A"] + r["B"] for r in rr]
        return [r["A"] + r["B"] + r["C"] for r in rr]

    res = {}
    econ = None
    for h in HORIZONS:
        valid = [r for r in rows if h in r["fwd"]]
        dh = sorted({r["date"] for r in valid})
        if len(dh) < 20:
            res[f"{h}s"] = {"note": "insuficiente", "n_dates": len(dh)}
            continue
        per = {f: {} for f in families}
        prev_names = None
        strat_rets, bench_rets, turnovers = [], [], []
        sector_count = defaultdict(int); sel_total = 0
        for di in range(12, len(dh)):
            d = dh[di]
            train = [r for r in valid if r["realize"][h] <= d]
            test = [r for r in valid if r["date"] == d]
            if len(train) < 80 or len(test) < 8:
                continue
            ytr = np.array([r["fwd"][h] for r in train]); yte = [r["fwd"][h] for r in test]
            preds = {}
            for fam in families:
                sc = StandardScaler().fit(np.array(X(train, fam)))
                mdl = Ridge(alpha=1.0).fit(sc.transform(np.array(X(train, fam))), ytr)
                p = mdl.predict(sc.transform(np.array(X(test, fam)))).tolist()
                preds[fam] = p
                ic = spearman_ic(p, yte)
                if ic is not None:
                    per[fam][d] = ic
            # economía (h=20, familia más rica disponible)
            if h == 20:
                fam = families[-1]
                order = sorted(range(len(test)), key=lambda k: preds[fam][k], reverse=True)
                top = order[: max(1, len(order) // 5)]
                names = set(test[k]["ticker"] for k in top)
                to = 1.0 if prev_names is None else len(names ^ prev_names) / max(1, len(names | prev_names))
                prev_names = names; turnovers.append(to)
                strat_rets.append(sum(yte[k] for k in top) / len(top) - to * COST)
                bench_rets.append(0.0)
                for k in top:
                    sector_count[test[k].get("sector", "Otro")] += 1; sel_total += 1
        res[f"{h}s"] = _summ(per, families, oos_start)
        if h == 20 and strat_rets:
            eq = [1.0]
            for r in strat_rets:
                eq.append(eq[-1] * (1 + r))
            peak = eq[0]; mdd = 0.0
            for v in eq:
                peak = max(peak, v); mdd = min(mdd, v / peak - 1)
            m = sum(strat_rets) / len(strat_rets)
            sd = (sum((x - m) ** 2 for x in strat_rets) / (len(strat_rets) - 1)) ** 0.5 if len(strat_rets) > 1 else 0
            econ = {
                "horizon": "20s", "family": families[-1], "rebalances": len(strat_rets),
                "cum_return_net": round(eq[-1] - 1, 4),
                "ann_sharpe": round((m / sd) * math.sqrt(252 / 20), 3) if sd > 0 else None,
                "avg_turnover": round(sum(turnovers) / len(turnovers), 3),
                "max_drawdown": round(mdd, 4),
                "sector_exposure": {k: round(v / sel_total, 3) for k, v in sorted(sector_count.items(), key=lambda x: -x[1])[:6]} if sel_total else {},
                "note": "retorno RELATIVO al mercado, neto de costos (turnover*10bps); benchmark equiponderado=0.",
            }
    return {"label": label, "companies": len({r["ticker"] for r in rows}),
            "observations": len(rows), "decision_dates": len(dec_dates),
            "first_date": dec_dates[0], "last_date": dec_dates[-1],
            "years": round((_d(dec_dates[-1]) - _d(dec_dates[0])).days / 365.0, 1),
            "oos_start_consulted": oos_start, "by_horizon": res, "economics_h20": econ}


def _summ(per, families, oos_start):
    def dev(f):
        return [per[f][d] for d in sorted(per[f]) if d < oos_start]

    def oos(f):
        return [per[f][d] for d in sorted(per[f]) if d >= oos_start]
    out = {}
    for f in families:
        dv = dev(f); m, lo, hi = block_boot(dv); ov = oos(f)
        out[f] = {"dev_ic": round(m, 4) if m is not None else None,
                  "dev_ci90": [round(lo, 4), round(hi, 4)] if lo is not None else None,
                  "dev_n": len(dv),
                  "oos_ic_consulted": round(sum(ov) / len(ov), 4) if ov else None, "oos_n": len(ov)}
    inc = {}
    pairs = [("B", "A")] + ([("C", "B")] if "C" in families else [])
    for x, y in pairs:
        common = [d for d in sorted(per[x]) if d in per[y] and d < oos_start]
        diffs = [per[x][d] - per[y][d] for d in common]
        m, lo, hi = block_boot(diffs)
        inc[f"{x}_minus_{y}"] = {"mean_diff": round(m, 4) if m is not None else None,
                                 "ci90": [round(lo, 4), round(hi, 4)] if lo is not None else None,
                                 "n": len(diffs), "defendable": bool(lo is not None and lo > 0)}
    out["incremental"] = inc
    return out


def run(provider, writer, tickers, rng="max"):
    prices = load_prices(provider, tickers, rng)
    if len(prices) < 10:
        return {"error": "universo insuficiente"}
    funds = read_fundamentals(writer, list(prices.keys()))
    macro, macro_span = read_macro(writer)
    sectors = read_sectors(writer, list(prices.keys()))

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

    funnel = {"grid_points": 0, "pass_price": 0, "pass_price_fund": 0, "pass_price_fund_macro": 0,
              "lost_fund": 0, "lost_macro": 0}
    rows_ab, rows_abc = [], []
    for t, b in prices.items():
        closes = [x["close"] for x in b]; vols = [x.get("volume") for x in b]; dts = [x["as_of"] for x in b]
        tl = funds.get(t, {}); sec = sectors.get(t, "Otro")
        for i in range(252, len(closes) - 1, STEP):
            funnel["grid_points"] += 1
            d = dts[i]
            fA = [momentum_12_1(closes, i), trailing_return(closes, i, 20), trailing_return(closes, i, 60),
                  trailing_return(closes, i, 120), reversal(closes, i, 5), trailing_vol(closes, i, 20),
                  trailing_vol(closes, i, 60), drawdown_from_high_at(closes, i, 252), volume_ratio(vols, i, 20, 60)]
            r60 = trailing_return(closes, i, 60); m60 = mkt_cum(dts, i, 60)
            fA.append((r60 - m60) if (r60 is not None and m60 is not None) else None)
            if any(x is None for x in fA):
                continue
            funnel["pass_price"] += 1
            fwd, realize = {}, {}
            for h in HORIZONS:
                if i + h < len(closes) and closes[i] > 0:
                    mf = mkt_cum(dts, i + h, h)
                    if mf is not None:
                        fwd[h] = closes[i + h] / closes[i] - 1.0 - mf; realize[h] = dts[i + h]
            if not fwd:
                continue
            fB = fund_features(tl, d)
            if fB is None:
                funnel["lost_fund"] += 1
                continue
            funnel["pass_price_fund"] += 1
            row = {"date": d, "ticker": t, "A": fA, "B": fB, "fwd": fwd, "realize": realize, "sector": sec}
            rows_ab.append(row)
            fC = macro_features(macro, d)
            if fC is None:
                funnel["lost_macro"] += 1
                continue
            funnel["pass_price_fund_macro"] += 1
            r2 = dict(row); r2["C"] = fC
            rows_abc.append(r2)

    out = {"experimental": True, "macro_availability": macro_span,
           "macro_excluded": ["WALCL (limitación PIT)"], "funnel": funnel,
           "validation_note": ("El periodo OOS (último 20%) YA fue consultado en la corrida previa; "
                               "se reporta como OOS histórico, no como holdout virgen. La validación "
                               "prospectiva real es la emisión diaria.")}
    out["experiment_AB"] = experiment(rows_ab, ["A", "B"], "A vs B (precio+fundamentales, historia máx)") if len(rows_ab) >= 300 else {"error": f"AB insuficiente ({len(rows_ab)})"}
    out["experiment_ABC"] = experiment(rows_abc, ["A", "B", "C"], "A vs B vs C (triple, historia máx)") if len(rows_abc) >= 300 else {"error": f"ABC insuficiente ({len(rows_abc)})"}
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
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300], "tb": traceback.format_exc()[-900:]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
