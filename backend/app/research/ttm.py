"""Reconstrucción TTM/LTM (últimos doce meses) desde EDGAR + EODHD, con calendarios fiscales propios.

TTM(flujo) = último FY + YTD actual − YTD comparable del año anterior (misma clase de YTD, ~1 año aparte).
Balance = último cierre reportado (instante), NO suma TTM. Diferencia FY / YTD / trimestral / TTM.
Reconcilia fuentes: OCF suele coincidir; el CAPEX de EDGAR (PaymentsToAcquirePropertyPlantAndEquipment)
puede subestimar (caso NVDA) ⇒ si una fuente da un capex implausiblemente bajo frente a la otra, se usa
la más completa y se registra. No inventa: si falta YTD, cae a FY y lo marca.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

FLOW_CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "RevenueFromContractsWithCustomers", "Revenue"],
    "operating_income": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "tax": ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestAndDebtExpense"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets", "PaymentsForCapitalImprovements"],
}
EODHD_Q_KEYS = {
    "revenue": ["totalRevenue"], "operating_income": ["operatingIncome", "ebit"],
    "net_income": ["netIncome"], "tax": ["incomeTaxExpense"], "pretax": ["incomeBeforeTax"],
    "interest_expense": ["interestExpense"], "ocf": ["totalCashFromOperatingActivities"],
    "capex": ["capitalExpenditures"],
}


def _d(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _dur(a, b):
    da, db = _d(a), _d(b)
    return (db - da).days if (da and db) else None


def _cls(days):
    if days is None:
        return "I"
    if 330 <= days <= 400:
        return "FY"
    if 250 <= days <= 290:
        return "9M"
    if 160 <= days <= 200:
        return "6M"
    if 80 <= days <= 100:
        return "Q"
    return None


def _edgar_periods(rows, concepts):
    best: Dict[Tuple, dict] = {}
    for r in rows:
        if r.get("concept") not in concepts:
            continue
        ps, pe, v, f = r.get("period_start"), r.get("period_end"), r.get("value"), r.get("filing_date")
        if v is None or not pe:
            continue
        c = _cls(_dur(ps, pe))
        if c is None:
            continue
        k = (ps, pe)
        if k not in best or (f or "") > (best[k]["filed"] or ""):
            best[k] = {"start": ps, "end": pe, "cls": c, "val": float(v), "filed": f}
    return sorted(best.values(), key=lambda x: (x["end"] or ""))


def _num(d, keys):
    for k in keys:
        v = (d or {}).get(k)
        if v not in (None, "", "None"):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def ttm_edgar(periods) -> Tuple[Optional[float], dict]:
    fy = [p for p in periods if p["cls"] == "FY"]
    if not fy:
        return None, {"metodo": "sin FY"}
    fy = fy[-1]
    ytd = [p for p in periods if p["cls"] in ("9M", "6M", "Q")]
    cur = ytd[-1] if ytd else None
    if not cur or _d(cur["end"]) <= _d(fy["end"]):
        return fy["val"], {"metodo": "solo FY (sin YTD posterior)", "fy": fy, "periodo": "FY", "fin": fy["end"]}
    prior = None
    ce = _d(cur["end"])
    for p in ytd:
        if p["cls"] == cur["cls"] and p is not cur:
            pe = _d(p["end"])
            if pe and 320 <= (ce - pe).days <= 410:
                prior = p
    if not prior:
        return fy["val"], {"metodo": "solo FY (sin YTD comparable)", "fy": fy, "periodo": "FY", "fin": fy["end"]}
    return fy["val"] + cur["val"] - prior["val"], {
        "metodo": "FY + YTD − YTD_prev", "clase": cur["cls"], "fin": cur["end"],
        "fy": {"fin": fy["end"], "val": fy["val"]}, "ytd": {"fin": cur["end"], "val": cur["val"]},
        "ytd_prev": {"fin": prior["end"], "val": prior["val"]}}


def ttm_eodhd(obj, field) -> Tuple[Optional[float], dict]:
    fin = (obj or {}).get("Financials", {}) or {}
    state = "Cash_Flow" if field in ("ocf", "capex") else "Income_Statement"
    q = (fin.get(state, {}) or {}).get("quarterly", {}) or {}
    items = sorted(q.items(), key=lambda kv: kv[0], reverse=True)[:4]
    vals = [_num(v, EODHD_Q_KEYS[field]) for _, v in items]
    if len(vals) < 4 or any(v is None for v in vals):
        return None, {"metodo": "EODHD <4 trimestres", "trimestres": [k for k, _ in items]}
    return sum(vals), {"metodo": "suma 4 trimestres EODHD", "trimestres": [k for k, _ in items], "valores": vals}


def reconstruct_ttm(edgar_rows: List[dict], eodhd_obj: dict) -> dict:
    """Devuelve {campo: {ttm, fuente, meta}} para flujos + controles. Flujos: revenue, operating_income,
    net_income, tax, pretax, interest_expense, ocf, capex (+ fcf derivado)."""
    out: Dict[str, dict] = {}
    controls: List[Tuple[str, bool, str]] = []
    for field, concepts in FLOW_CONCEPTS.items():
        e_val, e_meta = ttm_edgar(_edgar_periods(edgar_rows, concepts))
        o_val, o_meta = ttm_eodhd(eodhd_obj, field)
        chosen, src, meta = None, None, {}
        if e_val is not None and o_val is not None:
            # capex: EDGAR subestima a veces (PP&E-only). Si una es <50% de la otra, usar la mayor (más completa).
            if field == "capex" and min(abs(e_val), abs(o_val)) < 0.5 * max(abs(e_val), abs(o_val)):
                if abs(o_val) >= abs(e_val):
                    chosen, src = o_val, "EODHD"
                else:
                    chosen, src = e_val, "EDGAR"
                controls.append(("capex_fuentes_divergen", False,
                                 f"EDGAR {e_val/1e9:.1f}B vs EODHD {o_val/1e9:.1f}B ⇒ se usa {src} (más completa)"))
                meta = {"edgar": e_meta, "eodhd": o_meta}
            else:
                # discrepancia relativa
                rel = abs(e_val - o_val) / max(1.0, abs(e_val))
                chosen, src = e_val, "EDGAR"
                meta = e_meta
                if rel > 0.15:
                    controls.append((f"{field}_fuentes_divergen", False,
                                     f"EDGAR {e_val/1e9:.1f}B vs EODHD {o_val/1e9:.1f}B ({rel*100:.0f}%)"))
        elif e_val is not None:
            chosen, src, meta = e_val, "EDGAR", e_meta
        elif o_val is not None:
            chosen, src, meta = o_val, "EODHD", o_meta
        if chosen is not None:
            out[field] = {"ttm": chosen, "fuente": src, "meta": meta}

    # FCF TTM = OCF − |capex|
    if "ocf" in out and "capex" in out:
        out["fcf"] = {"ttm": out["ocf"]["ttm"] - abs(out["capex"]["ttm"]),
                      "fuente": f"{out['ocf']['fuente']}/{out['capex']['fuente']}",
                      "meta": "OCF − |capex|"}
        # control de consistencia OCF/CAPEX/FCF
        if out["ocf"]["ttm"] <= 0:
            controls.append(("ocf_no_positivo", False, f"OCF TTM {out['ocf']['ttm']/1e9:.1f}B"))

    # ¿hay TTM más reciente que el FY? (control item 3: FY cuando ya existe TTM)
    ocf_meta = out.get("ocf", {}).get("meta", {})
    tiene_ttm = isinstance(ocf_meta, dict) and ocf_meta.get("metodo", "").startswith("FY +")
    return {"ttm": out, "controles": controls, "tiene_ttm_real": tiene_ttm,
            "fin_ttm": ocf_meta.get("fin") if isinstance(ocf_meta, dict) else None}
