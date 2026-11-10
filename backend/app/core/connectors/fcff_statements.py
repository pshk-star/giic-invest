"""Capa ADITIVA de estados financieros para el futuro FCFF (P1.5.1).

NO sobrescribe `history.annual`, NO alimenta `valuation.ts` (DCF productivo) ni Advisor 2.2:
los Fair Values productivos no cambian. Funciones PURAS (sin red, sin pandas) sobre
`companyfacts` ya descargados y sobre series anuales EODHD ya normalizadas.

Cada campo lleva PROCEDENCIA y CALIDAD explícitas:
  - reported  : leído directo de un concepto de la taxonomía (EDGAR) o de EODHD.
  - derived   : calculado por identidad contable a partir de otros reportados (p. ej. pretax=NI+tax).
  - estimated : aproximado cuando no hay identidad exacta (se marca; el FCFF decidirá si lo admite).
  - na        : legítimamente no aplicable para el emisor (no cuenta como faltante).
  - missing   : debería existir y no se encontró (bloquea o degrada la elegibilidad).

Reutiliza `_best_annual`/`_currency_for` de normalize (misma semántica de período/forma/divisa).
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

from app.core.normalize import _best_annual, _best_instant, _currency_for

# --- Conceptos NUEVOS por taxonomía (aditivos; los core siguen en normalize.US_GAAP_MAP/IFRS_MAP) ---
FCFF_US_GAAP = {
    "dna": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization", "DepreciationAmortizationAndAccretion"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "interest": ["InterestExpense", "InterestExpenseDebt", "InterestAndDebtExpense"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "deferred_tax": ["DeferredIncomeTaxExpenseBenefit", "DeferredIncomeTaxesAndTaxCredits"],
    "finance_lease_capex": ["FinanceLeasePrincipalPayments", "RepaymentsOfLongTermCapitalLeaseObligations"],
    "ar": ["IncreaseDecreaseInAccountsReceivable"],
    "inv": ["IncreaseDecreaseInInventories"],
    "ap": ["IncreaseDecreaseInAccountsPayable", "IncreaseDecreaseInAccountsPayableTrade"],
    "wc_change": ["IncreaseDecreaseInOperatingCapital"],
}
FCFF_IFRS = {
    "dna": ["DepreciationAndAmortisationExpense",
            "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss"],
    "pretax": ["ProfitLossBeforeTax"],
    "tax": ["IncomeTaxExpenseContinuingOperations", "TaxExpenseIncome"],
    "interest": ["FinanceCosts", "InterestExpense"],
    "sbc": ["ShareBasedPaymentsExpense", "EmployeeBenefitsExpenseShareBasedPayments"],
    "deferred_tax": ["AdjustmentsForDeferredTaxExpense"],
    "finance_lease_capex": [],
    "ar": ["AdjustmentsForDecreaseIncreaseInTradeAndOtherReceivables"],
    "inv": ["AdjustmentsForDecreaseIncreaseInInventories"],
    "ap": ["AdjustmentsForIncreaseDecreaseInTradeAndOtherPayables"],
    "wc_change": [],
}

QUALITY = ("reported", "derived", "estimated", "na", "missing")
# Campos CRÍTICOS para un FCFF defendible (su ausencia degrada/bloquea; 'na' no cuenta como faltante).
CRITICAL_FCFF = ("revenue", "ebit", "tax_rate", "dna", "capex_total", "wc_change", "shares", "net_debt")


def _field(value, quality: str, source: str, concept: Optional[str] = None) -> dict:
    assert quality in QUALITY, quality
    return {"value": value, "quality": quality, "source": source, "concept": concept}


def _annual_map(facts, tax, names, ccy) -> Dict[str, float]:
    """{period_iso: valor} anual para el mejor concepto-variante (o vacío)."""
    return {d.isoformat(): v for d, v in _best_annual(facts, tax, names, ccy)} if names else {}


def build_edgar_fcff_fields(facts: dict, taxonomy: str, ccy: Optional[str],
                            core_by_year: Dict[str, dict]) -> Dict[str, Dict[str, dict]]:
    """Construye, por ejercicio, los campos NUEVOS del FCFF con calidad/procedencia.

    `core_by_year[period] = {revenue, net_income, operating_income, ocf, capex, cash, net_debt,...}`
    es la salida EDGAR existente (edgar_annual_history), que NO se modifica; aquí sólo se AÑADE.
    Devuelve `{period_iso: {campo: _field(...)}}`.
    """
    M = FCFF_US_GAAP if taxonomy == "us-gaap" else FCFF_IFRS
    ccy = ccy or _currency_for(facts, taxonomy, M["tax"]) or "USD"
    raw = {k: _annual_map(facts, taxonomy, M.get(k) or [], ccy) for k in M}
    out: Dict[str, Dict[str, dict]] = {}
    for period, core in core_by_year.items():
        ni = core.get("net_income")
        f: Dict[str, dict] = {}

        # D&A
        dna = raw["dna"].get(period)
        f["dna"] = _field(dna, "reported", "EDGAR", "dna") if dna is not None else _field(None, "missing", "EDGAR")

        # Impuesto y pretax (identidades: pretax = NI + tax ; tax_rate = tax/pretax)
        tax_v = raw["tax"].get(period)
        pretax = raw["pretax"].get(period)
        if pretax is None and tax_v is not None and ni is not None:
            pretax = ni + tax_v
            f["pretax"] = _field(pretax, "derived", "EDGAR", "NI+tax")
        elif pretax is not None:
            f["pretax"] = _field(pretax, "reported", "EDGAR", "pretax")
        else:
            f["pretax"] = _field(None, "missing", "EDGAR")
        f["tax"] = _field(tax_v, "reported", "EDGAR", "tax") if tax_v is not None else _field(None, "missing", "EDGAR")
        if tax_v is not None and pretax not in (None, 0):
            f["tax_rate"] = _field(tax_v / pretax, "derived", "EDGAR", "tax/pretax")
        else:
            f["tax_rate"] = _field(None, "missing", "EDGAR")

        # Intereses, SBC
        itr = raw["interest"].get(period)
        f["interest"] = _field(itr, "reported", "EDGAR", "interest") if itr is not None else _field(None, "missing", "EDGAR")
        sbc = raw["sbc"].get(period)
        f["sbc"] = _field(sbc, "reported", "EDGAR", "sbc") if sbc is not None else _field(None, "missing", "EDGAR")

        # CAPEX total = PP&E (core) + principal de leases financieros (si existe)
        ppe = core.get("capex")
        lease = raw["finance_lease_capex"].get(period)
        if ppe is not None:
            total = abs(ppe) + (abs(lease) if lease is not None else 0.0)
            q = "reported" if lease is not None else "derived"
            f["capex_total"] = _field(total, q, "EDGAR", "ppe+finance_lease" if lease is not None else "ppe_only")
            f["finance_lease_capex"] = _field(abs(lease), "reported", "EDGAR", "lease") if lease is not None else _field(0.0, "na", "EDGAR")
        else:
            f["capex_total"] = _field(None, "missing", "EDGAR")
            f["finance_lease_capex"] = _field(None, "missing", "EDGAR")

        # ΔWC: reportada directa, o derivada de componentes (AR+inv+AP), o estimada vía OCF-identidad
        wc = raw["wc_change"].get(period)
        if wc is not None:
            f["wc_change"] = _field(wc, "reported", "EDGAR", "wc_change")
        else:
            comps = [raw["ar"].get(period), raw["inv"].get(period), raw["ap"].get(period)]
            if any(c is not None for c in comps):
                # convención: aumento de activos = uso (resta); aumento de pasivos = fuente (suma)
                dwc = -(raw["ar"].get(period) or 0.0) - (raw["inv"].get(period) or 0.0) + (raw["ap"].get(period) or 0.0)
                f["wc_change"] = _field(dwc, "derived", "EDGAR", "AR+inv+AP")
            else:
                f["wc_change"] = _field(None, "missing", "EDGAR")
        out[period] = f
    return out


# --------- Integridad / reconciliación contable ---------
def reconcile_ocf(core: dict, extra: Dict[str, dict], tol: float = 0.20) -> dict:
    """OCF ≈ NI + D&A + SBC + impuestos diferidos − ΔWC (+ otros). Devuelve residual relativo y veredicto.
    No 'arregla' nada: marca si la identidad cierra dentro de tolerancia (detecta huecos/errores de signo)."""
    ni = core.get("net_income"); ocf = core.get("ocf")
    dna = extra.get("dna", {}).get("value")
    sbc = extra.get("sbc", {}).get("value") or 0.0
    wc = extra.get("wc_change", {}).get("value")
    if ni is None or ocf is None or dna is None or wc is None or ocf == 0:
        return {"ok": None, "reason": "insuficiente", "residual": None}
    implied = ni + dna + sbc + wc
    residual = (ocf - implied) / abs(ocf)
    return {"ok": abs(residual) <= tol, "residual": residual,
            "reason": "dentro_tolerancia" if abs(residual) <= tol else "residual_alto"}


def check_shares_scale(shares: Optional[float], market_cap: Optional[float],
                       min_shares: float = 1e5, max_implied_price: float = 2e6) -> Optional[str]:
    """Misma guarda que valuation.ts: acciones diluidas con escala inconsistente (caso MCD)."""
    if shares is None or shares <= 0:
        return "acciones diluidas ausentes o <=0"
    if shares < min_shares:
        return f"escala implausible ({shares:.3g} < 1e5): posible unidad en millones/miles"
    if market_cap and market_cap > 0:
        implied = market_cap / shares
        if implied > max_implied_price or implied < 1e-3:
            return f"precio implícito implausible ({implied:.3g})"
    return None


def integrity_report(core_by_year: Dict[str, dict], extra_by_year: Dict[str, Dict[str, dict]],
                     ccy: Optional[str], shares: Optional[float], market_cap: Optional[float],
                     today: Optional[date] = None, max_age_days: int = 450) -> dict:
    """Validaciones: moneda presente, escala de acciones, antigüedad del último anual, y
    reconciliación OCF por año. No exige 100%: reporta por campo."""
    today = today or date.today()
    periods = sorted(core_by_year)
    last = periods[-1] if periods else None
    age_days = None
    if last:
        try:
            p = last.split("-"); age_days = (today - date(int(p[0]), int(p[1]), int(p[2]))).days
        except (ValueError, IndexError):
            age_days = None
    recon = {y: reconcile_ocf(core_by_year[y], extra_by_year.get(y, {})) for y in periods}
    return {
        "currency": ccy, "currency_ok": bool(ccy),
        "shares_scale_issue": check_shares_scale(shares, market_cap),
        "last_period": last, "age_days": age_days,
        "stale": (age_days is not None and age_days > max_age_days),
        "ocf_reconciliation": recon,
    }


# --------- Elegibilidad FCFF (depende de calidad de datos críticos; 'na' no bloquea) ---------
def fcff_eligibility(core_last: dict, extra_last: Dict[str, dict], shares: Optional[float],
                     integrity: dict) -> dict:
    """status ∈ {eligible, degraded, ineligible}. 'na' no cuenta como faltante; stale o escala mala
    degradan/bloquean. No se fuerza 100% artificial."""
    present = {
        "revenue": core_last.get("revenue") is not None,
        "ebit": core_last.get("operating_income") is not None,
        "tax_rate": extra_last.get("tax_rate", {}).get("value") is not None,
        "dna": extra_last.get("dna", {}).get("value") is not None,
        "capex_total": extra_last.get("capex_total", {}).get("value") is not None,
        "wc_change": extra_last.get("wc_change", {}).get("value") is not None,
        "shares": shares is not None and shares > 0,
        "net_debt": core_last.get("net_debt") is not None,
    }
    na = {k for k in CRITICAL_FCFF if extra_last.get(k, {}).get("quality") == "na"}
    missing = [k for k in CRITICAL_FCFF if not present.get(k, False) and k not in na]
    if integrity.get("shares_scale_issue") or not present["revenue"] or not present["ebit"]:
        status = "ineligible"
    elif missing or integrity.get("stale"):
        status = "degraded"
    else:
        status = "eligible"
    return {"status": status, "missing_critical": missing, "na": sorted(na),
            "stale": bool(integrity.get("stale"))}


# --------- Fallback TSM: anexar ejercicio reciente desde EODHD con reconciliación de solape ---------
def merge_recent_annual_year(edgar_by_year: Dict[str, dict], eodhd_annual: Dict[str, Dict[str, float]],
                             edgar_data_end: Optional[date], overlap_tol: float = 0.02,
                             min_gap_days: int = 75) -> Tuple[Dict[str, dict], dict]:
    """Anexa el ejercicio EODHD MATERIALMENTE posterior al último EDGAR, SIN sobrescribir los años
    EDGAR ni mezclar monedas/períodos. Reconcilia el año de SOLAPE (EODHD vs EDGAR) en revenue/ni/ocf:
    si difiere > tol, el año anexado queda 'en_revision' (no se acepta automáticamente).

    `eodhd_annual[field][period_iso] = valor` para revenue/net_income/ocf/capex/cash/total_debt.
    Devuelve (serie_merged, log). La serie merged marca el año nuevo con source=EODHD + state.
    """
    log = {"appended": None, "state": None, "overlap_checks": {}, "reason": None}
    if not eodhd_annual:
        log["reason"] = "sin_eodhd"; return edgar_by_year, log
    rev_periods = sorted(eodhd_annual.get("revenue", {}))
    if not rev_periods:
        log["reason"] = "eodhd_sin_revenue_anual"; return edgar_by_year, log
    newest = rev_periods[-1]
    try:
        p = newest.split("-"); newest_d = date(int(p[0]), int(p[1]), int(p[2]))
    except (ValueError, IndexError):
        log["reason"] = "periodo_eodhd_invalido"; return edgar_by_year, log
    # ¿materialmente posterior al último EDGAR?
    if edgar_data_end is not None and (newest_d - edgar_data_end).days <= min_gap_days:
        log["reason"] = "no_materialmente_posterior"; return edgar_by_year, log
    if newest in edgar_by_year:
        log["reason"] = "ya_presente_en_edgar"; return edgar_by_year, log

    # Reconciliación del año de solape (el último EDGAR), si EODHD también lo trae.
    state = "verificado"
    if edgar_data_end is not None:
        ov = edgar_data_end.isoformat()
        for fld, core_key in (("revenue", "revenue"), ("net_income", "net_income"), ("ocf", "ocf")):
            ev = (edgar_by_year.get(ov) or {}).get(core_key)
            od = eodhd_annual.get(fld, {}).get(ov)
            if ev is not None and od not in (None, 0):
                diff = abs(od - ev) / abs(ev) if ev else None
                log["overlap_checks"][fld] = {"edgar": ev, "eodhd": od, "rel_diff": diff}
                if diff is not None and diff > overlap_tol:
                    state = "en_revision"
        if not log["overlap_checks"]:
            state = "en_revision"  # sin solape comparable → no se acepta ciegamente

    merged = dict(edgar_by_year)  # copia; NO muta EDGAR
    rev = eodhd_annual["revenue"][newest]
    ocf = eodhd_annual.get("ocf", {}).get(newest)
    capex = eodhd_annual.get("capex", {}).get(newest)
    cash = eodhd_annual.get("cash", {}).get(newest)
    debt = eodhd_annual.get("total_debt", {}).get(newest)
    ni = eodhd_annual.get("net_income", {}).get(newest)
    fcf = (ocf - abs(capex)) if (ocf is not None and capex is not None) else None
    nd = (debt - cash) if (debt is not None and cash is not None) else None
    merged[newest] = {
        "period_end": newest, "revenue": rev, "net_income": ni, "operating_income": None,
        "ocf": ocf, "capex": capex, "fcf": fcf, "cash": cash,
        "gross_debt": debt, "net_debt": nd,
        "op_margin": None, "net_margin": (ni / rev) if (ni is not None and rev) else None,
        "_source": "EODHD", "_state": state,
    }
    log["appended"] = newest; log["state"] = state
    return merged, log


def _to_date(x) -> Optional[date]:
    if isinstance(x, date):
        return x
    try:
        p = str(x)[:10].split("-"); return date(int(p[0]), int(p[1]), int(p[2]))
    except (ValueError, IndexError, TypeError):
        return None


def assemble_fcff_inputs(facts: dict, taxonomy: str, ccy: Optional[str],
                         edgar_history: list, edgar_data_end, shares: Optional[float],
                         market_cap: Optional[float], eodhd_annual: Optional[dict] = None,
                         today: Optional[date] = None) -> dict:
    """Orquesta la capa ADITIVA FCFF para un emisor: campos nuevos EDGAR + fallback EODHD del año
    reciente + integridad + elegibilidad. NO toca `history.annual` ni el DCF productivo.
    `edgar_history` = salida de edgar_annual_history (lista de records por año)."""
    core_by_year = {r["period_end"]: r for r in (edgar_history or []) if r and r.get("period_end")}
    extra = build_edgar_fcff_fields(facts, taxonomy, ccy, core_by_year)
    merged, merge_log = core_by_year, {"appended": None, "state": None, "reason": "sin_fallback"}
    if eodhd_annual:
        merged, merge_log = merge_recent_annual_year(core_by_year, eodhd_annual, _to_date(edgar_data_end))
    integ = integrity_report(merged, extra, ccy, shares, market_cap, today=today)
    last = sorted(merged)[-1] if merged else None
    elig = (fcff_eligibility(merged.get(last, {}), extra.get(last, {}), shares, integ)
            if last else {"status": "ineligible", "missing_critical": ["sin_historia"], "na": [], "stale": False})
    return {
        "schema": "fcff_inputs_v1", "currency": ccy, "taxonomy": taxonomy,
        "extra_by_year": extra, "merged_history": merged, "merge_log": merge_log,
        "integrity": integ, "eligibility": elig,
    }
