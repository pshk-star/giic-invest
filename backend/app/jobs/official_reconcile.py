"""Conciliación de TRES fuentes para determinar las cifras financieras REALES (no las de una API).

 1. EODHD (fundamentales normalizados, trimestres).
 2. SEC EDGAR — companyfacts XBRL (lo que el pipeline extrae hoy).
 3. ESTADOS OFICIALES — companyfacts COMPLETO de la SEC (todos los conceptos del 10-K/10-Q), con la
    presentación (accession/form/fecha) como soporte documental. Resuelve la selección de concepto/tag
    (p. ej. el capex real de NVDA, que el tag estándar subestima) enumerando TODOS los conceptos capex.

Regla de decisión: si las fuentes coinciden con el estado oficial, se usa; si discrepan, el oficial
resuelve y se documenta. No se reemplazan faltantes por cero. Métricas calculadas (FCF, ROIC, capital
invertido) se marcan como derivadas con su fórmula.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

from app.research.ttm import _cls, _dur, _d

# Patrones de concepto por métrica (para enumerar candidatos en los estados oficiales).
CAPEX_PATTERNS = re.compile(r"(PaymentsToAcquire(PropertyPlantAndEquipment|ProductiveAssets|"
                            r"MachineryAndEquipment|OtherPropertyPlantAndEquipment|IntangibleAssets)"
                            r"|PaymentsForCapitalImprovements|PaymentsForProceedsFromProductiveAssets"
                            r"|PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets)")
STD = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "RevenueFromContractsWithCustomers"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "equity": ["StockholdersEquity"],
    "shares": ["WeightedAverageNumberOfDilutedSharesOutstanding", "CommonStockSharesOutstanding"],
}


# Solo documentos de estados financieros (no proxy/8-K/otros): evita cifras resumidas o no comparables.
VALID_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "6-K"}


def _periods_from_facts(facts_usgaap: dict, concept: str) -> List[dict]:
    node = (facts_usgaap or {}).get(concept)
    if not node:
        return []
    out = {}
    for unit, rows in (node.get("units", {}) or {}).items():
        for f in rows:
            start, end, val = f.get("start"), f.get("end"), f.get("val")
            if val is None or not end:
                continue
            if (f.get("form") or "") not in VALID_FORMS:   # filtra DEF 14A, 8-K, etc.
                continue
            c = _cls(_dur(start, end))
            if c is None:
                continue
            k = (start, end)
            if k not in out or (f.get("filed") or "") > (out[k]["filed"] or ""):
                out[k] = {"start": start, "end": end, "cls": c, "val": float(val), "filed": f.get("filed"),
                          "accn": f.get("accn"), "form": f.get("form"), "fy": f.get("fy"), "fp": f.get("fp"),
                          "unit": unit}
    return sorted(out.values(), key=lambda x: (x["end"] or ""))


def _pick_recent_concept(usg: dict, cands: List[str]):
    """Entre conceptos equivalentes, elige el que tenga el FY más RECIENTE (evita tags en desuso)."""
    best = None
    for c in cands:
        pers = _periods_from_facts(usg, c)
        fy = _fy_latest(pers)
        if fy and (best is None or (fy["end"] or "") > (best[1]["end"] or "")):
            best = (c, fy, pers)
    return best  # (concepto, fy, periodos) o None


def _ttm(periods) -> Tuple[Optional[float], dict]:
    from app.research.ttm import ttm_edgar
    return ttm_edgar(periods)


def _fy_latest(periods):
    fy = [p for p in periods if p["cls"] == "FY"]
    return fy[-1] if fy else None


def reconcile_ticker(prov, t: str, eodhd_obj: dict) -> dict:
    facts = prov._facts(t)
    if not facts:
        return {"ticker": t, "error": "sin companyfacts en SEC (emisor no-US o sin XBRL)"}
    usg = (facts.get("facts", {}) or {}).get("us-gaap", {}) or {}
    cik = prov._cik.get(t.upper())

    # --- CAPEX: enumerar TODOS los conceptos candidatos (resolución de tag contra el estado oficial) ---
    capex_concepts = sorted([k for k in usg.keys() if CAPEX_PATTERNS.fullmatch(k)])
    capex_detail = []
    for c in capex_concepts:
        pers = _periods_from_facts(usg, c)
        fy = _fy_latest(pers)
        ttm_v, ttm_m = _ttm(pers)
        if fy or ttm_v is not None:
            capex_detail.append({"concepto": c, "fy_val": fy["val"] if fy else None,
                                 "fy_fin": fy["end"] if fy else None, "ttm": ttm_v,
                                 "accn": fy["accn"] if fy else None, "form": fy["form"] if fy else None,
                                 "filed": fy["filed"] if fy else None})
    # concepto capex oficial = el de mayor |valor FY| (la línea material del estado); los demás son parciales
    capex_detail.sort(key=lambda x: abs(x["fy_val"] or 0), reverse=True)
    capex_official = capex_detail[0] if capex_detail else None

    # --- EODHD TTM por métrica ---
    from app.research.ttm import ttm_eodhd
    eod = {m: ttm_eodhd(eodhd_obj, m)[0] for m in ("revenue", "operating_income", "net_income", "ocf", "capex")}

    # --- métricas estándar: oficial (SEC) vs EODHD, con TTM y soporte documental ---
    out_metrics = {}
    for m, cands in STD.items():
        chosen = None
        pick = _pick_recent_concept(usg, cands)   # concepto con FY más reciente (no tags en desuso)
        if pick:
            c, fy, pers = pick
            ttm_v, ttm_m = _ttm(pers)
            chosen = {"concepto": c, "fy_val": fy["val"], "fy_fin": fy["end"],
                      "ttm": ttm_v, "ttm_metodo": ttm_m.get("metodo"), "accn": fy["accn"],
                      "form": fy["form"], "filed": fy["filed"]}
        eod_v = eod.get(m)
        diff = None
        if chosen and chosen.get("ttm") and eod_v:
            diff = abs(chosen["ttm"] - eod_v) / max(1.0, abs(chosen["ttm"]))
        out_metrics[m] = {"oficial_SEC": chosen, "eodhd_ttm": eod_v,
                          "diff_rel": round(diff, 3) if diff is not None else None,
                          "estado": ("coincide" if (diff is not None and diff <= 0.05)
                                     else "discrepa" if diff is not None else "una_fuente")}

    # capex reconciliado
    capex_eod = eod.get("capex")
    capex_off_ttm = capex_official["ttm"] if capex_official else None
    capex_diff = (abs(capex_off_ttm - capex_eod) / max(1.0, abs(capex_off_ttm))) if (capex_off_ttm and capex_eod) else None

    # FCF derivado (oficial): OCF TTM − |capex TTM oficial|
    ocf_off = out_metrics["ocf"]["oficial_SEC"]["ttm"] if out_metrics["ocf"]["oficial_SEC"] else None
    fcf_off = (ocf_off - abs(capex_off_ttm)) if (ocf_off is not None and capex_off_ttm is not None) else None

    return {
        "ticker": t, "cik": cik,
        "capex_conceptos_enumerados": capex_detail,
        "capex_oficial": capex_official, "capex_eodhd_ttm": capex_eod,
        "capex_diff_rel": round(capex_diff, 3) if capex_diff is not None else None,
        "metricas": out_metrics,
        "FCF_oficial_TTM_derivado": fcf_off,
        "nota_doc": f"SEC Archives/edgar/data/{cik} (accession por métrica). Derivadas (FCF/ROIC/capital "
                    f"invertido) calculadas con fórmula explícita sobre conceptos oficiales.",
    }


# Conceptos de flujo para el motor (TTM) con árbitro oficial.
ENGINE_FLOWS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractsWithCustomers"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "tax": ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestAndDebtExpense"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
}


def observed_roiic(usg: dict) -> Optional[dict]:
    """ROIIC OBSERVADO = ΔNOPAT/ΔCapital invertido (vista financiación) de balances oficiales 10-K, en
    ventanas 3a y plurianual. Devuelve {roiic_3y, roiic_all, stable} o None si no es medible. NO fabrica
    nada: si falta EBIT/NOPAT o capital en los estados, la ventana queda vacía. 'stable' exige ambas
    ventanas positivas y consistentes (razón ≤ 3×), condición para usarlo en el motor (si no, supuesto
    conservador por defecto)."""
    try:
        from app.jobs.capital_roiic_diag import analyze
        ro = (analyze(usg) or {}).get("ROIIC_observado", {})
    except Exception:
        return None
    r3 = (ro.get("3a") or [None])[0]
    rall = (ro.get("plurianual") or [None])[0]
    if r3 is None and rall is None:
        return None
    stable = False
    if r3 and rall and r3 > 0 and rall > 0:
        hi, lo = max(r3, rall), min(r3, rall)
        stable = lo > 0 and hi / lo <= 3.0
    return {"roiic_3y": r3, "roiic_all": rall, "stable": stable}


def authoritative_ttm(prov, ticker: str, eodhd_obj: dict) -> dict:
    """TTM AUTORITATIVO por SUMA de 4 trimestres en VENTANA COMÚN (ttm.ttm_by_quarters) + ROIIC observado.

    Deriva trimestres de SEC (YTD-diff) y EODHD, fija una sola ventana (4 trimestres de OCF), suma cada
    métrica sobre ESA ventana y cruza SEC vs EODHD trimestre a trimestre. Garantiza que todas las métricas
    usen los MISMOS períodos (corrige el bug de ventanas distintas del selector FY+YTD−YTD). No completa
    con cero: si una fuente no cubre la ventana, se usa la otra; si ninguna, la métrica queda ausente.
    Adjunta el ROIIC observado (ΔNOPAT/ΔIC de balances oficiales) para la economía de reinversión.
    """
    from app.research.ttm import ttm_by_quarters
    facts = prov._facts(ticker)
    if not facts:
        return {"ttm": {}, "controles": [("sin_companyfacts", False, "emisor no-US/sin XBRL")], "fin_ttm": None}
    usg = (facts.get("facts", {}) or {}).get("us-gaap", {}) or {}
    res = ttm_by_quarters(usg, eodhd_obj, VALID_FORMS)
    res["roiic_observed"] = observed_roiic(usg)
    return res


def run(tickers: List[str]) -> dict:
    from app.providers.edgar import EDGARProvider
    # User-Agent de la SEC desde el secret (no se incrusta ningún correo personal en el código).
    ua = os.getenv("EDGAR_USER_AGENT") or "GIIC research noreply@giic.example"
    prov = EDGARProvider(user_agent=ua)
    prov._load_ciks()
    eodhd = {}
    if os.getenv("EODHD_API_KEY"):
        from app.core.connectors.eodhd import EodhdFundamentalsConnector
        conn = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
    out = {}
    for t in tickers:
        eod_obj = {}
        if os.getenv("EODHD_API_KEY"):
            try:
                _s, _a, eod_obj = conn._resolve(t)
                eod_obj = eod_obj or {}
            except Exception:
                eod_obj = {}
        try:
            out[t] = reconcile_ticker(prov, t, eod_obj)
        except Exception as e:
            out[t] = {"ticker": t, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    return out


def main(argv=None):
    tickers = [t.upper() for t in (argv or sys.argv[1:])] or ["NVDA", "META", "NFLX", "ASML", "TSM", "PFE", "AMGN", "ADBE"]
    print(json.dumps(run(tickers), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
