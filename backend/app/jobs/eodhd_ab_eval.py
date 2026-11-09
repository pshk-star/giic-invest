"""E3.4 — evaluación A/B ANTES (EDGAR) vs DESPUÉS (EDGAR+EODHD) sobre datos REALES (solo lectura).

Mide, sobre las operativas de la batería, la cobertura A y la cobertura VIGENTE B antes y después de
sumar el conector EODHD. EDGAR sigue siendo el ancla oficial; EODHD aporta el período interino fresco
para los 4 campos núcleo (revenue/net_income/ocf/cash). Un interino fresco que EDGAR no tiene queda
`parcial` usable (no bloqueado); un valor que difiere de EDGAR en mismo período/moneda se marca
inconsistente y NO cuenta. No desarrolla Fair Value; no toca predicciones.

Uso: EODHD_API_KEY + EDGAR_USER_AGENT en env; python -m app.jobs.eodhd_ab_eval
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date

from app.core.normalize import _at, _best_annual, _best_instant, _ttm_best, _concept
from app.core.quality import field_applies, is_financial_sector
from app.core.recency import assess_recency
from app.core.connectors.eodhd import EodhdFundamentalsConnector, reconcile_quality
from app.providers.edgar import parse_companyfacts
from app.services.identity import resolve_identity
from app.jobs.coverage_battery import UNIVERSE, ADR_SEED, FX
from app.jobs.e3_coverage_diag import _pick_tax, _ref_period, _parse_date
from app.jobs.e3_final_eval import (_submissions_recency, _fiscal_cadence, _present, _segment,
                                    FV_FIELDS, CORP_CATS, EVAL_DATE)

CORE = ("revenue", "net_income", "ocf", "cash")   # lo que EODHD aporta con calidad suficiente


def edgar_annual_series(facts, tax, M, ccy):
    out = {}
    for field, concepts, inst in (("revenue", M["rev"], False), ("net_income", M["ni"], False),
                                  ("ocf", M["ocf"], False), ("cash", M["cash"], True)):
        pts = (_best_instant if inst else _best_annual)(facts, tax, concepts, ccy)
        out[field] = {d.isoformat(): v for d, v in pts}
    return out


def _data_end(facts, tax, M, ccy, f):
    ni_ttm = _ttm_best(facts, tax, M["ni"], ccy)
    return _parse_date(ni_ttm["end"]) if (ni_ttm and ni_ttm.get("end")) else (_parse_date(f.as_of) if f.as_of else None)


def run() -> dict:
    ua = os.getenv("EDGAR_USER_AGENT", "")
    key = os.getenv("EODHD_API_KEY", "")
    if not ua or "@" not in ua:
        return {"error": "sin EDGAR_USER_AGENT"}
    if not key:
        return {"error": "sin EODHD_API_KEY (no se evalúa 'después')"}
    import httpx
    cli = httpx.Client(timeout=40.0, headers={"User-Agent": ua}, follow_redirects=True)
    tk = cli.get("https://www.sec.gov/files/company_tickers.json").json()
    cikmap = {r["ticker"].upper(): int(r["cik_str"]) for r in tk.values()}
    conn = EodhdFundamentalsConnector(api_key=key)

    cat_of = {t: c for c, ts in UNIVERSE.items() for t in ts}
    tickers = [t for c in CORP_CATS for t in UNIVERSE[c]]
    per = {}
    eodhd_calls = 0
    for t in tickers:
        cik = cikmap.get(t.upper())
        if not cik:
            continue
        lag, latest_report, sic = _submissions_recency(cli, cik)
        time.sleep(0.12)
        try:
            r = cli.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
            if r.status_code != 200:
                continue
            facts = r.json()
        except Exception:
            continue
        itype = None
        try:
            itype = resolve_identity(t).get("instrument_type")
        except Exception:
            pass
        f = parse_companyfacts(facts, t, price=None, instrument_type=itype, sic=sic,
                               adr_ratio=ADR_SEED.get(t.upper(), 1.0), fx_map=FX)
        if f.data_quality in ("no_aplica", "indeterminado"):
            continue
        tax, ccy, M = _pick_tax(facts)
        ref = _ref_period(facts, tax, M, ccy)
        cadence = _fiscal_cadence(facts, tax, M, ccy)
        data_end = _data_end(facts, tax, M, ccy, f)
        later = bool(latest_report and data_end and (latest_report - data_end).days > 20)
        rec = assess_recency(data_end, EVAL_DATE, cadence_days=cadence, lag_days=lag,
                             later_report_exists=later, window=f.eps_ttm_window)
        blocked = f.data_quality == "bloqueado"
        seg = _segment(cat_of[t], sic)

        # BEFORE (EDGAR): estado por campo.
        before = {}
        for fld in FV_FIELDS:
            present = _present(facts, tax, M, ref, f, fld)
            if blocked:
                before[fld] = "bloqueado"
            elif present:
                before[fld] = "vigente" if rec["estado"] == "vigente" else "presente_no_vigente"
            elif not field_applies(fld, sic):
                before[fld] = "no_aplica"
            else:
                before[fld] = "faltante"

        # EODHD: fetch + conciliación contra EDGAR (mismo período/moneda).
        eo = {}
        anomalies = []
        try:
            got = conn.fetch([t]) or {}
            eodhd_calls += 1
            fm = got.get(t, {})
            if fm:
                series = edgar_annual_series(facts, tax, M, ccy)
                eo_ccy = next((pf.currency for pf in fm.values() if pf.currency), None)
                same_ccy = bool(eo_ccy and eo_ccy.upper() == (ccy or "").upper())
                fm = reconcile_quality(fm, series, same_ccy)
                eo = fm
                for k, pf in fm.items():
                    if pf.quality == "inconsistente":
                        anomalies.append({"campo": k, "valor": pf.value, "proc": pf.provenance})
        except Exception as e:
            eo = {"_error": str(e)[:80]}

        # AFTER: los 4 núcleo pasan a vigente si EODHD tiene un interino FRESCO usable (no inconsistente).
        after = dict(before)
        eodhd_fresh = {}
        for core in CORE:
            pf = eo.get(core) if isinstance(eo, dict) else None   # 'core' = observación interina
            if pf and pf.quality in ("verificado", "parcial"):
                pe = _parse_date(pf.period)
                if pe and (data_end is None or pe > data_end):
                    after[core] = "vigente_eodhd"
                    eodhd_fresh[core] = {"period": pf.period, "quality": pf.quality, "filing": pf.as_of, "currency": pf.currency}

        per[t] = {"segmento": seg, "sic": sic, "before": before, "after": after,
                  "data_end_edgar": data_end.isoformat() if data_end else None,
                  "eodhd_fresh": eodhd_fresh, "anomalias_eodhd": anomalies,
                  "eodhd_symbol": next((pf.provenance for pf in eo.values() if hasattr(pf, "provenance")), None) if isinstance(eo, dict) else None}
        time.sleep(0.12)

    # Agregación A/B antes/después por segmento.
    def ab(states_map, tickers_in):
        A_num = den = B_num = 0
        for t in tickers_in:
            for fld, st in states_map(t).items():
                if st == "no_aplica":
                    continue
                den += 1
                if st in ("vigente", "presente_no_vigente", "vigente_eodhd"):
                    A_num += 1
                if st in ("vigente", "vigente_eodhd"):
                    B_num += 1
        return {"A": round(A_num / den, 3) if den else None, "B": round(B_num / den, 3) if den else None,
                "den": den, "A_n": A_num, "B_n": B_num}

    segs = sorted({per[t]["segmento"] for t in per})
    by_seg = {}
    for s in segs:
        ts = [t for t in per if per[t]["segmento"] == s]
        by_seg[s] = {"n": len(ts),
                     "antes": ab(lambda t: per[t]["before"], ts),
                     "despues": ab(lambda t: per[t]["after"], ts)}
    total = {"antes": ab(lambda t: per[t]["before"], list(per)),
             "despues": ab(lambda t: per[t]["after"], list(per))}

    anomalies_all = {t: per[t]["anomalias_eodhd"] for t in per if per[t]["anomalias_eodhd"]}
    return {
        "n_operativas": len(per), "fecha": EVAL_DATE.isoformat(),
        "consumo_api_eodhd_llamadas": eodhd_calls,
        "total_antes_despues": total,
        "por_segmento": by_seg,
        "anomalias_eodhd_vs_edgar": anomalies_all,
        "por_ticker": per,
    }


def main(argv=None):
    try:
        print(json.dumps(run(), indent=2, default=str, ensure_ascii=False))
        return 0
    except Exception as e:
        import traceback
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300], "tb": traceback.format_exc()[-900:]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
