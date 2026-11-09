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
import re
import sys
import time
from datetime import date

from app.core.normalize import _ttm_best
from app.core.recency import assess_recency
from app.core.connectors.eodhd import EodhdFundamentalsConnector, reconcile_quality
from app.core.connectors.fundamentals_enrich import edgar_annual_series, is_materially_fresher
from app.providers.edgar import parse_companyfacts
from app.services.identity import resolve_identity
from app.jobs.coverage_battery import UNIVERSE, ADR_SEED, FX
from app.jobs.e3_coverage_diag import _pick_tax, _ref_period, _parse_date
from app.jobs.e3_final_eval import (_submissions_recency, _fiscal_cadence, _segment,
                                    build_edgar_states, CORP_CATS, EVAL_DATE)

CORE = ("revenue", "net_income", "ocf", "cash")   # lo que EODHD aporta con calidad suficiente


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
    # Un ticker puede colisionar con varias CIK (p. ej. XOM → 34088 Exxon y una entidad reciente).
    # Se conservan TODAS las candidatas (orden: emisor primario = CIK más baja primero) y se elige
    # la que tenga datos reales; evita tomar una entidad equivocada por "último gana".
    cik_cands = {}
    for r in tk.values():
        cik_cands.setdefault(r["ticker"].upper(), []).append(int(r["cik_str"]))
    for k in cik_cands:
        cik_cands[k] = sorted(set(cik_cands[k]))
    conn = EodhdFundamentalsConnector(api_key=key)

    cat_of = {t: c for c, ts in UNIVERSE.items() for t in ts}
    tickers = [t for c in CORP_CATS for t in UNIVERSE[c]]
    per = {}
    eodhd_calls = 0

    def _fetch_facts(client, c):   # companyfacts con reintento (pueden llegar incompletos/throttled)
        for _try in range(3):
            try:
                r = client.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json")
                if r.status_code == 200:
                    j = r.json()
                    if (j.get("facts", {}) or {}).get("us-gaap") or (j.get("facts", {}) or {}).get("ifrs-full"):
                        return j
            except Exception:
                pass
            time.sleep(0.6)
        return None

    for t in tickers:
        cands = cik_cands.get(t.upper(), [])
        if not cands:
            continue
        # Resolución robusta ticker→CIK. Una sigla puede mapear a varias entidades (XOM → 34088
        # Exxon y una CIK reciente sin datos). Con una sola candidata, comportamiento idéntico al
        # previo; con varias, se elige la que tenga serie oficial real, con fallback a la primera
        # con hechos us-gaap/ifrs. Evita el bug de "última gana" que tomaba la entidad equivocada.
        cik = None
        facts = None
        if len(cands) == 1:
            facts = _fetch_facts(cli, cands[0])
            cik = cands[0] if facts is not None else None
        else:
            fallback = None
            for cand in cands:
                j = _fetch_facts(cli, cand)
                if j is None:
                    continue
                if fallback is None:
                    fallback = (cand, j)
                tax_c, ccy_c, M_c = _pick_tax(j)
                s_c = edgar_annual_series(j, tax_c, M_c, ccy_c)
                if s_c["revenue"] or s_c["net_income"]:
                    cik, facts = cand, j
                    break
            if facts is None and fallback is not None:
                cik, facts = fallback
        if facts is None:
            continue
        # Fallback de IDENTIFICACIÓN (mismo criterio que EDGARProvider): si la entidad resuelta por
        # company_tickers.json no tiene serie anual, usar el filer con 10-K reales (browse-edgar).
        # Corrige XOM (tickers.json → 2115436 sin datos; el 10-K de Exxon está bajo 34088).
        from app.providers.edgar import _has_annual_core
        cik_tickersjson = cik
        cik_corregida = False
        if not _has_annual_core(facts):
            try:
                ae = cli.get("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                             f"&ticker={t}&type=10-K&count=1&output=atom")
                mm = re.search(r"<cik>\s*(\d+)\s*</cik>", ae.text or "")
                alt = int(mm.group(1)) if mm else None
                if alt and alt != cik:
                    jj = _fetch_facts(cli, alt)
                    if jj is not None and _has_annual_core(jj):
                        facts, cik, cik_corregida = jj, alt, True
                time.sleep(0.12)
            except Exception:
                pass
        lag, latest_report, sic = _submissions_recency(cli, cik)
        time.sleep(0.12)
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
        series = edgar_annual_series(facts, tax, M, ccy)   # serie oficial (para conciliación y diagnóstico)
        edgar_diag = {"parse_as_of": f.as_of, "data_quality": f.data_quality, "taxonomy": tax,
                      "currency": ccy, "n_revenue": len(series["revenue"]), "n_net_income": len(series["net_income"]),
                      "ultimo_revenue": (max(series["revenue"]) if series["revenue"] else None),
                      "ultimo_net_income": (max(series["net_income"]) if series["net_income"] else None),
                      "n_usgaap_concepts": len((facts.get("facts", {}) or {}).get("us-gaap", {})),
                      "has_NetIncomeLoss": "NetIncomeLoss" in (facts.get("facts", {}) or {}).get("us-gaap", {}),
                      "cik": cik, "cik_tickersjson": cik_tickersjson, "cik_corregida": cik_corregida,
                      "cik_candidatas": cik_cands.get(t.upper(), [])}
        # Si tras el fallback de identificación la serie sigue vacía (us-gaap/USD), probar
        # companyconcept para distinguir companyfacts PARCIAL de ausencia real (cobertura).
        if not series["revenue"] and tax == "us-gaap":
            try:
                cc = cli.get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/NetIncomeLoss.json")
                if cc.status_code == 200:
                    rows = [r for r in cc.json().get("units", {}).get("USD", [])
                            if str(r.get("form", "")).startswith("10-K") and r.get("start")]
                    edgar_diag["companyconcept_NI_ultimo"] = max((r["end"] for r in rows), default=None)
                time.sleep(0.12)
            except Exception as e:
                edgar_diag["companyconcept_NI_ultimo"] = type(e).__name__
        later = bool(latest_report and data_end and (latest_report - data_end).days > 20)
        rec = assess_recency(data_end, EVAL_DATE, cadence_days=cadence, lag_days=lag,
                             later_report_exists=later, window=f.eps_ttm_window)
        blocked = f.data_quality == "bloqueado"
        seg = _segment(cat_of[t], sic)

        # BEFORE (EDGAR): estado por campo (lógica compartida con el enriquecimiento productivo).
        before = build_edgar_states(facts, tax, M, ref, f, sic, blocked, rec["estado"])

        # EODHD: fetch + conciliación contra EDGAR (mismo período/moneda).
        eo = {}
        anomalies = []
        try:
            got = conn.fetch([t]) or {}
            eodhd_calls += 1
            fm = got.get(t, {})
            if fm:
                eo_ccy = next((pf.currency for pf in fm.values() if pf.currency), None)
                same_ccy = bool(eo_ccy and eo_ccy.upper() == (ccy or "").upper())
                fm = reconcile_quality(fm, series, same_ccy)
                eo = fm
                for k, pf in fm.items():
                    if pf.quality == "inconsistente":
                        anomalies.append({"campo": k, "valor": pf.value, "proc": pf.provenance})
        except Exception as e:
            eo = {"_error": str(e)[:80]}

        # AFTER: EODHD sólo mejora un campo si (a) EDGAR NO estaba ya vigente (preservar el oficial
        # verificado) y (b) el interino EODHD es un período fiscal MATERIALMENTE posterior (>75 días
        # = al menos un trimestre nuevo, no jitter de calendario del mismo ejercicio). Equivalencia
        # de período: no se cuenta mejora ficticia por una fecha calendario ligeramente posterior.
        after = dict(before)
        eodhd_fresh = {}
        for core in CORE:
            pf = eo.get(core) if isinstance(eo, dict) else None   # 'core' = observación interina
            if not (pf and pf.quality in ("verificado", "parcial")):
                continue
            pe = _parse_date(pf.period)
            if not pe:
                continue
            if before[core] == "vigente":
                continue  # EDGAR ya vigente → preservar dato oficial, sin mejora
            if not is_materially_fresher(pe, data_end):
                continue  # mismo período económico (jitter de fechas) → no es más fresco
            if before[core] in ("presente_no_vigente", "faltante"):
                after[core] = "vigente_eodhd"
                eodhd_fresh[core] = {"period": pf.period, "quality": pf.quality, "filing": pf.as_of,
                                     "currency": pf.currency, "edgar_data_end": data_end.isoformat() if data_end else None}

        # Matriz DCF: estado por campo necesario para flujo descontado.
        dcf_label = {"vigente": "vigente/verificado", "vigente_eodhd": "vigente/parcial(EODHD)",
                     "presente_no_vigente": "desactualizado", "bloqueado": "bloqueado",
                     "faltante": "faltante", "no_aplica": "no_aplica"}
        dcf = {k: dcf_label.get(after.get(k), after.get(k))
               for k in ("fcf_ttm", "ocf", "capex", "net_debt", "cash", "diluted_shares")}
        dcf["currency"] = ccy
        per[t] = {"segmento": seg, "sic": sic, "before": before, "after": after,
                  "data_end_edgar": data_end.isoformat() if data_end else None,
                  "eodhd_fresh": eodhd_fresh, "anomalias_eodhd": anomalies, "edgar_diag": edgar_diag,
                  "dcf_matriz": dcf,
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
