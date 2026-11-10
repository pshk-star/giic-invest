"""Capa ADITIVA de estados financieros para el futuro FCFF (P1.5.1).

NO sobrescribe `history.annual`, NO alimenta `valuation.ts` (DCF productivo) ni Advisor 2.2:
los Fair Values productivos no cambian. Funciones PURAS (sin red, sin pandas) sobre
`companyfacts` (EDGAR) y la serie anual completa del conector EODHD.

Procedencia y CALIDAD explícitas por campo:
  reported | derived | estimated | na | missing.
Cada campo lleva además source (EDGAR/EODHD), period y currency cuando aplica.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

from app.core.normalize import _best_annual, _currency_for

# --- Conceptos NUEVOS por taxonomía (aditivos) ---
FCFF_US_GAAP = {
    "dna": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization", "DepreciationAmortizationAndAccretion"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "interest": ["InterestExpense", "InterestExpenseDebt", "InterestAndDebtExpense"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "finance_lease_capex": ["FinanceLeasePrincipalPayments", "RepaymentsOfLongTermCapitalLeaseObligations"],
    "capex_other": ["PaymentsToAcquireIntangibleAssets", "PaymentsToDevelopSoftware"],
    "ar": ["IncreaseDecreaseInAccountsReceivable"],
    "inv": ["IncreaseDecreaseInInventories"],
    "ap": ["IncreaseDecreaseInAccountsPayable", "IncreaseDecreaseInAccountsPayableTrade"],
    "wc_change": ["IncreaseDecreaseInOperatingCapital"],
}
FCFF_IFRS = {
    # D&A de TSM se etiqueta como ajuste de flujo IFRS; se incluyen varias variantes y se verifica cuál cae.
    "dna": ["AdjustmentsForDepreciationAndAmortisationExpense",
            "DepreciationAndAmortisationExpense",
            "AdjustmentsForDepreciationAndAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
            "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
            "AdjustmentsForDepreciationExpense"],
    "pretax": ["ProfitLossBeforeTax"],
    "tax": ["IncomeTaxExpenseContinuingOperations", "TaxExpenseIncome"],
    "interest": ["FinanceCosts", "InterestExpense"],
    "sbc": ["ShareBasedPaymentsExpense", "EmployeeBenefitsExpenseShareBasedPayments"],
    "finance_lease_capex": [],
    "capex_other": ["PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"],
    "ar": ["AdjustmentsForDecreaseIncreaseInTradeAndOtherReceivables"],
    "inv": ["AdjustmentsForDecreaseIncreaseInInventories"],
    "ap": ["AdjustmentsForIncreaseDecreaseInTradeAndOtherPayables"],
    "wc_change": [],
}

QUALITY = ("reported", "derived", "estimated", "na", "missing")
# Críticos para un FCFF defendible. capex_ppe (no un total auto-sumado). 'na' no cuenta como faltante.
CRITICAL_FCFF = ("revenue", "ebit", "tax_rate", "dna", "capex_ppe", "wc_change", "shares", "net_debt")


def _f(value, quality: str, source: str, concept: Optional[str] = None, **extra) -> dict:
    assert quality in QUALITY, quality
    d = {"value": value, "quality": quality, "source": source, "concept": concept}
    d.update(extra)
    return d


def _annual_map(facts, tax, names, ccy) -> Dict[str, float]:
    return {d.isoformat(): v for d, v in _best_annual(facts, tax, names, ccy)} if names else {}


def _annual_map_with_concept(facts, tax, names, ccy) -> Tuple[Dict[str, float], Optional[str]]:
    """Como _annual_map pero devuelve también QUÉ concepto-variante cayó (para registrar el tag IFRS real)."""
    for n in names or []:
        m = {d.isoformat(): v for d, v in _best_annual(facts, tax, [n], ccy)}
        if m:
            return m, n
    return {}, None


def build_edgar_fcff_fields(facts: dict, taxonomy: str, ccy: Optional[str],
                            core_by_year: Dict[str, dict]) -> Dict[str, Dict[str, dict]]:
    """Campos NUEVOS por ejercicio desde EDGAR, con calidad/procedencia. CAPEX se mantiene en
    COMPONENTES separados (PP&E, leases financieros, otros) — NO se auto-suma un total."""
    M = FCFF_US_GAAP if taxonomy == "us-gaap" else FCFF_IFRS
    ccy = ccy or _currency_for(facts, taxonomy, M["tax"]) or "USD"
    raw = {k: _annual_map(facts, taxonomy, M.get(k) or [], ccy) for k in M if k != "dna"}
    dna_map, dna_concept = _annual_map_with_concept(facts, taxonomy, M.get("dna") or [], ccy)
    out: Dict[str, Dict[str, dict]] = {}
    for period, core in core_by_year.items():
        ni = core.get("net_income")
        f: Dict[str, dict] = {}
        dna = dna_map.get(period)
        f["dna"] = _f(dna, "reported", "EDGAR", dna_concept) if dna is not None else _f(None, "missing", "EDGAR")
        tax_v = raw["tax"].get(period); pretax = raw["pretax"].get(period)
        if pretax is None and tax_v is not None and ni is not None:
            pretax = ni + tax_v; f["pretax"] = _f(pretax, "derived", "EDGAR", "NI+tax")
        elif pretax is not None:
            f["pretax"] = _f(pretax, "reported", "EDGAR", "pretax")
        else:
            f["pretax"] = _f(None, "missing", "EDGAR")
        f["tax"] = _f(tax_v, "reported", "EDGAR", "tax") if tax_v is not None else _f(None, "missing", "EDGAR")
        f["tax_rate"] = (_f(tax_v / pretax, "derived", "EDGAR", "tax/pretax")
                         if (tax_v is not None and pretax not in (None, 0)) else _f(None, "missing", "EDGAR"))
        itr = raw["interest"].get(period)
        f["interest"] = _f(itr, "reported", "EDGAR", "interest") if itr is not None else _f(None, "missing", "EDGAR")
        sbc = raw["sbc"].get(period)
        f["sbc"] = _f(sbc, "reported", "EDGAR", "sbc") if sbc is not None else _f(None, "missing", "EDGAR")

        # CAPEX en COMPONENTES SEPARADOS (no se suman): PP&E (núcleo), leases financieros, otros.
        ppe = core.get("capex")
        f["capex_ppe"] = _f(abs(ppe), "reported", "EDGAR", "ppe") if ppe is not None else _f(None, "missing", "EDGAR")
        lease = raw["finance_lease_capex"].get(period)
        f["finance_lease_capex"] = (_f(abs(lease), "reported", "EDGAR", "finance_lease") if lease is not None
                                    else _f(0.0, "na", "EDGAR"))
        other = raw["capex_other"].get(period)
        f["capex_other"] = _f(abs(other), "reported", "EDGAR", "other_investing") if other is not None else _f(None, "missing", "EDGAR")

        # ΔWC: completa (línea directa) vs aproximación por componentes AR/inv/AP.
        wc = raw["wc_change"].get(period)
        if wc is not None:
            f["wc_change"] = _f(wc, "reported", "EDGAR", "wc_change", completeness="complete")
        else:
            comps = {"ar": raw["ar"].get(period), "inv": raw["inv"].get(period), "ap": raw["ap"].get(period)}
            if any(v is not None for v in comps.values()):
                dwc = -(comps["ar"] or 0.0) - (comps["inv"] or 0.0) + (comps["ap"] or 0.0)
                f["wc_change"] = _f(dwc, "derived", "EDGAR", "AR+inv+AP", completeness="approx_ar_inv_ap",
                                    components={k: v for k, v in comps.items() if v is not None})
            else:
                f["wc_change"] = _f(None, "missing", "EDGAR", completeness=None)
        out[period] = f
    return out


# --------- Integridad ---------
def reconcile_ocf(core: dict, extra: Dict[str, dict], complete_tol: float = 0.05,
                  partial_tol: float = 0.25) -> dict:
    """OCF ≈ NI + D&A + SBC + ΔWC es una identidad PARCIAL (faltan impuestos diferidos y otros no-caja).
    Clasifica: complete | partial | unidentified | insufficient. NO rechaza datos: el residual pequeño/
    medio es esperable por partidas legítimas que no capturamos."""
    ni, ocf = core.get("net_income"), core.get("ocf")
    dna = extra.get("dna", {}).get("value")
    sbc = extra.get("sbc", {}).get("value") or 0.0
    wc = extra.get("wc_change", {}).get("value")
    if ni is None or ocf is None or dna is None or wc is None or ocf == 0:
        return {"level": "insufficient", "residual": None, "reason": "faltan componentes para la identidad parcial"}
    residual = (ocf - (ni + dna + sbc + wc)) / abs(ocf)
    level = "complete" if abs(residual) <= complete_tol else ("partial" if abs(residual) <= partial_tol else "unidentified")
    return {"level": level, "residual": residual,
            "note": "identidad PARCIAL (sin impuestos diferidos/otros no-caja); residual no rechaza el dato"}


def check_shares_scale(shares: Optional[float], market_cap: Optional[float],
                       min_shares: float = 1e5, max_implied_price: float = 2e6) -> Optional[str]:
    if shares is None or shares <= 0:
        return "acciones diluidas ausentes o <=0"
    if shares < min_shares:
        return f"escala implausible ({shares:.3g} < 1e5): posible unidad en millones/miles"
    if market_cap and market_cap > 0:
        implied = market_cap / shares
        if implied > max_implied_price or implied < 1e-3:
            return f"precio implícito implausible ({implied:.3g})"
    return None


def integrity_report(core_by_year, extra_by_year, ccy, shares, market_cap,
                     today: Optional[date] = None, max_age_days: int = 450) -> dict:
    today = today or date.today()
    periods = sorted(core_by_year)
    last = periods[-1] if periods else None
    age_days = None
    if last:
        try:
            p = last.split("-"); age_days = (today - date(int(p[0]), int(p[1]), int(p[2]))).days
        except (ValueError, IndexError):
            age_days = None
    return {
        "currency": ccy, "currency_ok": bool(ccy),
        "shares_scale_issue": check_shares_scale(shares, market_cap),
        "last_period": last, "age_days": age_days,
        "stale": (age_days is not None and age_days > max_age_days),
        "ocf_reconciliation": {y: reconcile_ocf(core_by_year[y], extra_by_year.get(y, {})) for y in periods},
    }


# --------- Elegibilidad ---------
def fcff_eligibility(core_last: dict, extra_last: Dict[str, dict], shares: Optional[float],
                     integrity: dict, is_financial: bool = False, last_state: Optional[str] = None) -> dict:
    """status ∈ {eligible, degraded, ineligible, na}. Financiera ⇒ na (FCFF no aplica). 'na' por campo no
    cuenta como faltante. Año anexado 'en_revision' ⇒ no eligible (críticos sin verificar)."""
    if is_financial:
        return {"status": "na", "reason": "institución financiera: FCFF no aplica (usar exceso de retorno/DDM)",
                "missing_critical": [], "na": list(CRITICAL_FCFF), "stale": False}
    present = {
        "revenue": core_last.get("revenue") is not None,
        "ebit": core_last.get("operating_income") is not None,
        "tax_rate": extra_last.get("tax_rate", {}).get("value") is not None,
        "dna": extra_last.get("dna", {}).get("value") is not None,
        "capex_ppe": extra_last.get("capex_ppe", {}).get("value") is not None,
        "wc_change": extra_last.get("wc_change", {}).get("value") is not None,
        "shares": shares is not None and shares > 0,
        "net_debt": core_last.get("net_debt") is not None,
    }
    na = {k for k in CRITICAL_FCFF if extra_last.get(k, {}).get("quality") == "na"}
    missing = [k for k in CRITICAL_FCFF if not present.get(k, False) and k not in na]
    if integrity.get("shares_scale_issue") or not present["revenue"] or not present["ebit"]:
        status = "ineligible"
    elif last_state == "en_revision" or missing or integrity.get("stale"):
        status = "degraded"
    else:
        status = "eligible"
    return {"status": status, "missing_critical": missing, "na": sorted(na),
            "stale": bool(integrity.get("stale")), "last_state": last_state}


# --------- Fallback: serie anual completa EODHD ---------
def _to_date(x) -> Optional[date]:
    if isinstance(x, date):
        return x
    try:
        p = str(x)[:10].split("-"); return date(int(p[0]), int(p[1]), int(p[2]))
    except (ValueError, IndexError, TypeError):
        return None


def merge_eodhd_series(edgar_by_year: Dict[str, dict], eodhd_full: dict,
                       edgar_data_end: Optional[date], overlap_tol: float = 0.03,
                       min_gap_days: int = 75) -> Tuple[Dict[str, dict], Dict[str, dict], dict]:
    """Anexa el ejercicio EODHD materialmente posterior con TODOS los campos, SIN tocar EDGAR.
    Reconcilia el SOLAPE (último EDGAR) en revenue/net_income/ocf/operating_income con tolerancia
    justificada; documenta diffs. state='verificado' sólo si todos los solapes comparables reconcilian;
    si falta solape o diverge → 'en_revision' (no se acepta automáticamente).
    Devuelve (core_merged, extra_appended, log). extra_appended = campos FCFF del año nuevo (EODHD)."""
    by = (eodhd_full or {}).get("by_field") or {}
    ccy = (eodhd_full or {}).get("currency")
    log = {"appended": None, "state": None, "overlap": {}, "reason": None, "currency": ccy}
    rev = by.get("revenue") or {}
    if not rev:
        log["reason"] = "eodhd_sin_revenue_anual"; return edgar_by_year, {}, log
    newest = sorted(rev)[-1]
    nd = _to_date(newest)
    if nd is None:
        log["reason"] = "periodo_invalido"; return edgar_by_year, {}, log
    if edgar_data_end is not None and (nd - edgar_data_end).days <= min_gap_days:
        log["reason"] = "no_materialmente_posterior"; return edgar_by_year, {}, log
    if newest in edgar_by_year:
        log["reason"] = "ya_presente_en_edgar"; return edgar_by_year, {}, log

    state = "verificado"
    if edgar_data_end is not None:
        ov = edgar_data_end.isoformat()
        checks = {}
        for fld, core_key in (("revenue", "revenue"), ("net_income", "net_income"),
                              ("ocf", "ocf"), ("operating_income", "operating_income")):
            ev = (edgar_by_year.get(ov) or {}).get(core_key)
            od = (by.get(fld) or {}).get(ov)
            if ev is not None and od not in (None, 0):
                diff = abs(od - ev) / abs(ev) if ev else None
                checks[fld] = {"edgar": ev, "eodhd": od, "rel_diff": diff, "tol": overlap_tol,
                               "ok": (diff is not None and diff <= overlap_tol)}
                if diff is not None and diff > overlap_tol:
                    state = "en_revision"
        log["overlap"] = checks
        if not checks:
            state = "en_revision"  # sin solape comparable → no aceptar a ciegas

    def g(field):
        return (by.get(field) or {}).get(newest)

    capex = g("capex"); ocf = g("ocf"); cash = g("cash"); debt = g("total_debt"); ni = g("net_income")
    rev_v = g("revenue")
    fcf = (ocf - abs(capex)) if (ocf is not None and capex is not None) else None
    netd = (debt - cash) if (debt is not None and cash is not None) else None
    merged = dict(edgar_by_year)
    merged[newest] = {
        "period_end": newest, "revenue": rev_v, "net_income": ni, "operating_income": g("operating_income"),
        "ocf": ocf, "capex": (abs(capex) if capex is not None else None), "fcf": fcf,
        "cash": cash, "gross_debt": debt, "net_debt": netd,
        "op_margin": (g("operating_income") / rev_v) if (g("operating_income") is not None and rev_v) else None,
        "net_margin": (ni / rev_v) if (ni is not None and rev_v) else None,
        "_source": "EODHD", "_state": state,
    }
    # Campos FCFF del año nuevo desde EODHD (procedencia EODHD, estado del merge).
    def ef(field, concept):
        v = g(field)
        return _f(v, "reported", "EODHD", concept, state=state) if v is not None else _f(None, "missing", "EODHD")
    pretax = g("pretax"); tax = g("tax")
    extra_appended = {
        "dna": ef("dna", "eodhd:depreciation"),
        "tax": ef("tax", "eodhd:incomeTaxExpense"),
        "pretax": ef("pretax", "eodhd:incomeBeforeTax"),
        "tax_rate": (_f(tax / pretax, "derived", "EODHD", "tax/pretax", state=state)
                     if (tax is not None and pretax not in (None, 0)) else _f(None, "missing", "EODHD")),
        "interest": ef("interest", "eodhd:interestExpense"),
        "sbc": ef("sbc", "eodhd:stockBasedCompensation"),
        "capex_ppe": _f(abs(capex), "reported", "EODHD", "eodhd:capex", state=state) if capex is not None else _f(None, "missing", "EODHD"),
        "finance_lease_capex": _f(None, "missing", "EODHD"),
        "wc_change": _f(g("wc_change"), "reported", "EODHD", "eodhd:changeInWorkingCapital",
                        completeness="eodhd_aggregate", state=state) if g("wc_change") is not None else _f(None, "missing", "EODHD"),
    }
    log["appended"] = newest; log["state"] = state
    return merged, extra_appended, log


def backfill_missing_dna_from_eodhd(extra_by_year: Dict[str, Dict[str, dict]], eodhd_full: dict) -> int:
    """Rellena D&A de los años EDGAR donde falta (p. ej. TSM IFRS) con el mismo período de EODHD,
    marcando source=EODHD. No sobrescribe un D&A ya reportado por EDGAR. Devuelve cuántos rellenó."""
    dna = ((eodhd_full or {}).get("by_field") or {}).get("dna") or {}
    n = 0
    for period, fields in extra_by_year.items():
        cur = fields.get("dna") or {}
        if cur.get("value") is None and dna.get(period) is not None:
            fields["dna"] = _f(dna[period], "reported", "EODHD", "eodhd:depreciation")
            n += 1
    return n


def assemble_fcff_inputs(facts: dict, taxonomy: str, ccy: Optional[str], edgar_history: list,
                         edgar_data_end, shares: Optional[float], market_cap: Optional[float],
                         eodhd_full: Optional[dict] = None, is_financial: bool = False,
                         today: Optional[date] = None) -> dict:
    """Orquesta la capa aditiva FCFF para un emisor. NO toca history.annual ni el DCF productivo."""
    core_by_year = {r["period_end"]: r for r in (edgar_history or []) if r and r.get("period_end")}
    extra = build_edgar_fcff_fields(facts, taxonomy, ccy, core_by_year)
    merged, merge_log, dna_backfilled = core_by_year, {"appended": None, "state": None, "reason": "sin_fallback"}, 0
    if eodhd_full:
        merged, extra_appended, merge_log = merge_eodhd_series(core_by_year, eodhd_full, _to_date(edgar_data_end))
        if merge_log.get("appended"):
            extra[merge_log["appended"]] = extra_appended
        dna_backfilled = backfill_missing_dna_from_eodhd(extra, eodhd_full)
    # Acciones: EDGAR (diluidas ponderadas) o, si faltan, EODHD (shares outstanding, base distinta — se anota).
    shares_source = "EDGAR"
    if (shares is None or shares <= 0) and eodhd_full:
        esh = ((eodhd_full.get("by_field") or {}).get("shares") or {})
        if esh:
            shares = esh[sorted(esh)[-1]]; shares_source = "EODHD:commonStockSharesOutstanding(base_distinta)"
    integ = integrity_report(merged, extra, ccy, shares, market_cap, today=today)
    last = sorted(merged)[-1] if merged else None
    last_state = (merged.get(last, {}) or {}).get("_state")
    elig = (fcff_eligibility(merged.get(last, {}), extra.get(last, {}), shares, integ,
                             is_financial=is_financial, last_state=last_state)
            if last else {"status": "ineligible", "missing_critical": ["sin_historia"], "na": [], "stale": False})
    return {
        "schema": "fcff_inputs_v2", "currency": ccy, "taxonomy": taxonomy,
        "shares": shares, "shares_source": shares_source, "is_financial": is_financial,
        "extra_by_year": extra, "merged_history": merged, "merge_log": merge_log,
        "dna_backfilled_from_eodhd": dna_backfilled,
        "integrity": integ, "eligibility": elig,
    }
