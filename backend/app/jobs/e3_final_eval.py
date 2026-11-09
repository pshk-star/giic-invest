"""E3 — EVALUACIÓN FINAL (solo lectura): dos indicadores separados sobre las 63 operativas.

A. Cobertura financiera: % de campos Fair Value recuperados con valor válido y trazable (aplicables
   al emisor; los no_aplica por sector NO cuentan como hueco).
B. Cobertura financiera VIGENTE: % de campos suficientemente recientes/comparables para una
   valoración ACTUAL (A ∩ vigente). La vigencia usa la cadencia del propio emisor y la existencia de
   reportes posteriores (capa core/recency), sin umbrales universales.

Desglose por tipo: us_equities, adr_ifrs, bancos_y_financieras, otros. Marca bloqueados (MU),
no_aplica por sector, y limitaciones. No escribe nada; no desarrolla Fair Value.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime

from app.core.normalize import (_at, _best_annual, _best_instant, _ttm_best, _concept)
from app.core.quality import field_applies, is_financial_sector
from app.core.recency import reporting_cadence_days, typical_filing_lag_days, assess_recency
from app.providers.edgar import parse_companyfacts
from app.services.identity import resolve_identity
from app.jobs.coverage_battery import UNIVERSE, ADR_SEED, FX
from app.jobs.e3_coverage_diag import _pick_tax, _ref_period, _parse_date

CORP_CATS = ["us_large", "us_mid_small", "multi_class", "recent_splits", "financials", "adr_ifrs", "regression"]
PERIODIC = {"10-Q", "10-K", "20-F", "40-F", "6-K"}
FV_FIELDS = ["revenue", "operating_income", "net_income", "eps", "diluted_shares",
             "ocf", "capex", "fcf_annual", "fcf_ttm", "net_debt", "cash", "gross_debt"]
EVAL_DATE = date(2026, 11, 7)


def _submissions_recency(cli, cik):
    """Del calendario de presentaciones (submissions): retardo típico de publicación y el reportDate
    (cierre fiscal) MÁS RECIENTE entre formas periódicas → para detectar reportes POSTERIORES. La
    CADENCIA NO se deriva de aquí (los 6-K agrupan fechas y la distorsionan); se calcula aparte de los
    períodos fiscales reales. Distingue reportDate (cierre) de filingDate (publicación)."""
    try:
        j = cli.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
    except Exception:
        return None, None, None
    rec = j.get("filings", {}).get("recent", {})
    forms = rec.get("form", []); fdates = rec.get("filingDate", []); rdates = rec.get("reportDate", [])
    ends, pairs = [], []
    for i, fm in enumerate(forms):
        if fm not in PERIODIC:
            continue
        rd = _parse_date(rdates[i]) if i < len(rdates) else None
        fd = _parse_date(fdates[i]) if i < len(fdates) else None
        if rd:
            ends.append(rd)
            if fd:
                pairs.append((rd, fd))
    lag = typical_filing_lag_days(pairs)
    latest_report = max(ends) if ends else None
    sic = j.get("sic")
    try:
        sic = int(sic) if sic not in (None, "") else None
    except (ValueError, TypeError):
        sic = None
    return lag, latest_report, sic


def _fiscal_cadence(facts, tax, M, ccy):
    """Cadencia REAL del emisor desde los cierres de sus períodos fiscales tagueados (duration facts
    de utilidad neta): ~91 trimestral, ~182 semestral, ~365 anual. Evita el ruido de fechas de 6-K."""
    ends = []
    for n in M["ni"]:
        for r in _concept(facts, tax, n, ccy):
            s, e = _parse_date(r.get("start")), _parse_date(r.get("end"))
            if s and e and 60 <= (e - s).days <= 400:
                ends.append(e)
    return reporting_cadence_days(ends)


def _present(facts, tax, M, ref, f, field):
    """¿El campo tiene valor válido recuperado? (presencia para indicador A)."""
    if field == "revenue":
        return _at(_best_annual(facts, tax, M["rev"], f.currency), ref) is not None
    if field == "operating_income":
        return _at(_best_annual(facts, tax, M["op_income"], f.currency), ref) is not None
    if field == "net_income":
        return _at(_best_annual(facts, tax, M["ni"], f.currency), ref) is not None or (f.eps is not None)
    if field == "eps":
        return f.eps is not None
    if field == "diluted_shares":
        return f.diluted_shares is not None
    if field == "ocf":
        return _at(_best_annual(facts, tax, M["ocf"], f.currency), ref) is not None
    if field == "capex":
        return (_at(_best_annual(facts, tax, M["capex"], f.currency), ref) is not None
                or _at(_best_annual(facts, tax, M.get("capex_alt", []), f.currency), ref) is not None)
    if field == "fcf_annual":
        return f.fcf_annual is not None
    if field == "fcf_ttm":
        return f.fcf_ttm is not None
    if field == "net_debt":
        return f.net_debt is not None
    if field == "cash":
        return f.cash_and_sti is not None
    if field == "gross_debt":
        return f.gross_debt is not None
    return False


def build_edgar_states(facts, tax, M, ref, f, sic, blocked, rec_estado, fields=None):
    """Estado de vigencia/presencia de EDGAR por campo: vigente | presente_no_vigente | faltante |
    bloqueado | no_aplica. Es EXACTAMENTE el loop BEFORE del A/B, extraído para que la evaluación y
    el enriquecimiento productivo usen la MISMA lógica de vigencia y presencia (sin divergir)."""
    states = {}
    for fld in (fields or FV_FIELDS):
        present = _present(facts, tax, M, ref, f, fld)
        if blocked:
            states[fld] = "bloqueado"
        elif present:
            states[fld] = "vigente" if rec_estado == "vigente" else "presente_no_vigente"
        elif not field_applies(fld, sic):
            states[fld] = "no_aplica"
        else:
            states[fld] = "faltante"
    return states


def _segment(cat, sic):
    if is_financial_sector(sic):
        return "bancos_y_financieras"
    if cat == "adr_ifrs":
        return "adr_ifrs"
    if cat in ("us_large", "us_mid_small", "multi_class", "recent_splits", "regression"):
        return "us_equities"
    return "otros"


def run() -> dict:
    ua = os.getenv("EDGAR_USER_AGENT", "")
    if not ua or "@" not in ua:
        return {"error": "sin EDGAR_USER_AGENT"}
    import httpx
    cli = httpx.Client(timeout=40.0, headers={"User-Agent": ua}, follow_redirects=True)
    tk = cli.get("https://www.sec.gov/files/company_tickers.json").json()
    cikmap = {r["ticker"].upper(): int(r["cik_str"]) for r in tk.values()}

    cat_of = {t: c for c, ts in UNIVERSE.items() for t in ts}
    tickers = [t for c in CORP_CATS for t in UNIVERSE[c]]
    per = {}
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
        # Fin del dato REALMENTE reflejado: para TTM rodante es el corte interino; para anual-como-TTM
        # es el cierre anual. NO el ancla de referencia (que suele ser el último anual). Esto evita
        # marcar como "no vigente" a quien ya incorporó su trimestre más reciente.
        ni_ttm = _ttm_best(facts, tax, M["ni"], ccy)
        data_end = _parse_date(ni_ttm["end"]) if (ni_ttm and ni_ttm.get("end")) else (_parse_date(f.as_of) if f.as_of else None)
        # Reporte POSTERIOR no incorporado = un reportDate materialmente más nuevo que el fin del dato.
        later = bool(latest_report and data_end and (latest_report - data_end).days > 20)
        recency = assess_recency(data_end, EVAL_DATE, cadence_days=cadence, lag_days=lag,
                                 later_report_exists=later, window=f.eps_ttm_window)
        blocked = f.data_quality == "bloqueado"
        states = {}
        for fld in FV_FIELDS:
            present = _present(facts, tax, M, ref, f, fld)
            # PRESENCIA antes que sector: si el emisor SÍ reporta la métrica, cuenta (aunque sea una
            # financiera diversificada). Sólo se marca no_aplica una métrica industrial AUSENTE en una
            # financiera (no es un hueco a rellenar). Bloqueado nunca cuenta como válido.
            if blocked:
                states[fld] = "bloqueado"
            elif present:
                states[fld] = "vigente" if recency["estado"] == "vigente" else "presente_no_vigente"
            elif not field_applies(fld, sic):
                states[fld] = "no_aplica"
            else:
                states[fld] = "faltante"
        per[t] = {"segmento": _segment(cat_of[t], sic), "sic": sic, "data_quality": f.data_quality,
                  "period_end": f.as_of, "data_end": data_end.isoformat() if data_end else None,
                  "window": f.eps_ttm_window, "recency": recency["estado"],
                  "recency_razon": recency.get("razon"), "cadencia_dias": cadence,
                  "latest_report": latest_report.isoformat() if latest_report else None,
                  "states": states}

    # Agregación A y B por segmento.
    segs = ["us_equities", "adr_ifrs", "bancos_y_financieras", "otros"]
    def agg(tickers_in):
        A_num = A_den = B_num = 0
        for t in tickers_in:
            for fld, st in per[t]["states"].items():
                if st == "no_aplica":
                    continue                 # no cuenta como hueco ni como cubierto
                A_den += 1
                if st in ("vigente", "presente_no_vigente"):
                    A_num += 1
                if st == "vigente":
                    B_num += 1
        return {"n_empresas": len(tickers_in),
                "A_cobertura": round(A_num / A_den, 3) if A_den else None,
                "B_cobertura_vigente": round(B_num / A_den, 3) if A_den else None,
                "campos_aplicables": A_den, "campos_presentes": A_num, "campos_vigentes": B_num}
    by_seg = {s: agg([t for t in per if per[t]["segmento"] == s]) for s in segs}
    total = agg(list(per))

    # Por campo (global operativas): A y B.
    def field_ab(fld):
        app = [t for t in per if per[t]["states"][fld] != "no_aplica"]
        if not app:
            return {"A": None, "B": None, "n_aplicable": 0}
        A = sum(1 for t in app if per[t]["states"][fld] in ("vigente", "presente_no_vigente"))
        B = sum(1 for t in app if per[t]["states"][fld] == "vigente")
        return {"A": round(A / len(app), 3), "B": round(B / len(app), 3), "n_aplicable": len(app)}
    por_campo = {fld: field_ab(fld) for fld in FV_FIELDS}

    bloqueados = {t: per[t]["period_end"] for t in per if per[t]["data_quality"] == "bloqueado"}
    no_vigentes = {t: {"period_end": per[t]["period_end"], "razon": per[t]["recency_razon"]}
                   for t in per if per[t]["recency"] == "desactualizado"}

    return {
        "n_operativas": len(per), "fecha_evaluacion": EVAL_DATE.isoformat(),
        "indicadores_totales": total,
        "por_segmento": by_seg,
        "por_campo": por_campo,
        "bloqueados": bloqueados,
        "no_vigentes(dato valido pero no actual)": no_vigentes,
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
