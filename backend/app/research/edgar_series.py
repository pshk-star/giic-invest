"""P1 — Adaptador EDGAR -> serie del driver (by_field) con CAPITAL INVERTIDO real.

Construye la misma estructura `by_field` que `eodhd_annual_series_full` (periodos ISO -> valor por
campo) PERO desde los hechos point-in-time ingeridos de SEC EDGAR (tabla `fundamentals_pit`), SIN
depender de EODHD. La diferencia material frente a EODHD: EDGAR permite reconstruir el

    CAPITAL INVERTIDO real = equity + deuda total − caja

y separar la D&A OPERATIVA de la AMORTIZACIÓN DE INTANGIBLES ADQUIRIDOS
(dna_operativa = D&A total − amortización de adquisiciones). Con esto el driver deja de aproximar el
capital desde el capex (causa del bloqueo de PFE/AMGN) y calcula s2c/ROIC/reinversión reales.

Point-in-time: para cada (concepto, año fiscal) se toma el hecho con el `filing_date` MÁS RECIENTE
disponible hasta `as_of` (incorpora reexpresiones sin look-ahead en backtest). No inventa: si un campo
no está en EDGAR para un periodo, queda ausente (None) y el driver lo trata como tal.

Campos producidos (compatibles con el driver): revenue, net_income, operating_income, tax, ocf, capex
(negativo), dna (OPERATIVA), wc_change, cash, total_debt, shares, equity, invested_capital. Extra en
meta por periodo: dna_total, amort_acq, goodwill, intangibles (diagnóstico/auditoría).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

# --- Mapeo concepto EDGAR -> campo canónico. Orden = prioridad (primero disponible gana por periodo). ---
# Conceptos de FLUJO (duración ~anual): P&L y flujo de caja.
FLOW_MAP: Dict[str, List[str]] = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "RevenueFromContractsWithCustomers", "Revenue"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_income": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "tax": ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations", "TaxExpense"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "dna_total": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
                  "DepreciationAndAmortization", "DepreciationAndAmortisationExpense",
                  "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss"],
    "amort_acq": ["AmortizationOfIntangibleAssets", "AmortisationIntangibleAssetsOtherThanGoodwill"],
    "shares_diluted_wavg": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}
# Conceptos INSTANTE (balance; period_start nulo).
INSTANT_MAP: Dict[str, List[str]] = {
    "equity": ["StockholdersEquity", "Equity"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "CashAndCashEquivalents"],
    "debt_lt_total": ["LongTermDebt"],
    "debt_lt_noncurrent": ["LongTermDebtNoncurrent", "NoncurrentPortionOfLongtermBorrowings", "Borrowings"],
    "debt_current": ["LongTermDebtCurrent", "DebtCurrent", "CurrentPortionOfLongtermBorrowings"],
    "debt_short": ["ShortTermBorrowings", "ShorttermBorrowings"],
    "assets_current": ["AssetsCurrent", "CurrentAssets"],
    "liabilities_current": ["LiabilitiesCurrent", "CurrentLiabilities"],
    "shares_outstanding": ["CommonStockSharesOutstanding"],
    "goodwill": ["Goodwill"],
    "intangibles": ["FiniteLivedIntangibleAssetsNet", "IntangibleAssetsNetExcludingGoodwill",
                    "IntangibleAssetsOtherThanGoodwill"],
}


def _d(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _is_annual(period_start: Optional[str], period_end: Optional[str]) -> bool:
    a, b = _d(period_start), _d(period_end)
    if not a or not b:
        return False
    return 330 <= (b - a).days <= 400


def _fy(period_end: Optional[str]) -> Optional[int]:
    e = _d(period_end)
    return e.year if e else None


def _pick_pit(rows: List[dict], concepts: List[str], want_annual: Optional[bool],
              as_of: Optional[date]) -> Dict[int, Tuple[float, str, str]]:
    """Para los `concepts` dados (en orden de prioridad), devuelve {año_fiscal: (valor, period_end, concepto)}.

    PIT: por (concepto, año) toma el `filing_date` más reciente <= as_of. Entre conceptos del mapa,
    gana el de mayor prioridad que tenga dato ese año. want_annual=True exige duración anual (flujo),
    False exige instante (balance), None no filtra.
    """
    # best_by_concept[concept][fy] = (filing_date, value, period_end)
    best: Dict[str, Dict[int, Tuple[str, float, str]]] = {}
    for r in rows:
        c = r.get("concept")
        if c not in concepts:
            continue
        ps, pe = r.get("period_start"), r.get("period_end")
        if want_annual is True and not _is_annual(ps, pe):
            continue
        if want_annual is False and _d(ps) is not None:
            continue  # instante: sin period_start
        fy = _fy(pe)
        val = r.get("value")
        filed = r.get("filing_date")
        if fy is None or val is None or not filed:
            continue
        if as_of is not None and _d(filed) and _d(filed) > as_of:
            continue  # look-ahead: hecho publicado después de la fecha de corte
        slot = best.setdefault(c, {})
        prev = slot.get(fy)
        # más reciente por filing_date; desempate por period_end más tardío (cierre fiscal correcto)
        if prev is None or (filed, pe or "") > (prev[0], prev[2] or ""):
            slot[fy] = (filed, float(val), pe or "")
    # resolver prioridad entre conceptos
    out: Dict[int, Tuple[float, str, str]] = {}
    years = sorted({fy for c in best for fy in best[c]})
    for fy in years:
        for c in concepts:  # orden de prioridad
            if c in best and fy in best[c]:
                _filed, v, pe = best[c][fy]
                out[fy] = (v, pe, c)
                break
    return out


def build_series_from_rows(rows: List[dict], as_of: Optional[str] = None) -> dict:
    """Construye {'currency', 'by_field', 'meta'} desde filas fundamentals_pit de UN ticker.

    `rows`: lista de dicts con las columnas de fundamentals_pit (concept, period_start, period_end,
    value, filing_date, unit, taxonomy, ...). `as_of`: ISO date de corte PIT (None = todo lo conocido).
    """
    asof = _d(as_of)
    # moneda: unidad mayoritaria de ingresos (USD/EUR/TWD...)
    ccy = None
    rev_units: Dict[str, int] = {}
    for r in rows:
        if r.get("concept") in FLOW_MAP["revenue"] and r.get("unit"):
            u = str(r["unit"]).upper()
            rev_units[u] = rev_units.get(u, 0) + 1
    if rev_units:
        ccy = max(rev_units, key=rev_units.get)

    flow: Dict[str, Dict[int, Tuple[float, str, str]]] = {
        f: _pick_pit(rows, concepts, True, asof) for f, concepts in FLOW_MAP.items()
    }
    inst: Dict[str, Dict[int, Tuple[float, str, str]]] = {
        f: _pick_pit(rows, concepts, False, asof) for f, concepts in INSTANT_MAP.items()
    }

    def end_iso(fy: int, *tables: Dict[int, Tuple[float, str, str]]) -> str:
        for t in tables:
            if fy in t and t[fy][1]:
                return t[fy][1]
        return f"{fy}-12-31"

    years = sorted({fy for t in list(flow.values()) + list(inst.values()) for fy in t})
    by: Dict[str, Dict[str, float]] = {}
    meta: Dict[str, Dict[str, Optional[float]]] = {}

    def put(field: str, period: str, value: Optional[float]):
        if value is None:
            return
        by.setdefault(field, {})[period] = value

    prev_wc: Optional[float] = None
    for fy in years:
        p = end_iso(fy, flow["revenue"], inst["equity"], inst["cash"])
        rev = flow["revenue"].get(fy, (None,))[0]
        ni = flow["net_income"].get(fy, (None,))[0]
        ebit = flow["operating_income"].get(fy, (None,))[0]
        tax = flow["tax"].get(fy, (None,))[0]
        ocf = flow["ocf"].get(fy, (None,))[0]
        capex = flow["capex"].get(fy, (None,))[0]
        dna_total = flow["dna_total"].get(fy, (None,))[0]
        amort = flow["amort_acq"].get(fy, (None,))[0]
        sh_w = flow["shares_diluted_wavg"].get(fy, (None,))[0]

        equity = inst["equity"].get(fy, (None,))[0]
        cash = inst["cash"].get(fy, (None,))[0]
        d_lt_total = inst["debt_lt_total"].get(fy, (None,))[0]
        d_lt_nc = inst["debt_lt_noncurrent"].get(fy, (None,))[0]
        d_cur = inst["debt_current"].get(fy, (None,))[0]
        d_short = inst["debt_short"].get(fy, (None,))[0]
        ac = inst["assets_current"].get(fy, (None,))[0]
        lc = inst["liabilities_current"].get(fy, (None,))[0]
        sh_o = inst["shares_outstanding"].get(fy, (None,))[0]
        gw = inst["goodwill"].get(fy, (None,))[0]
        intang = inst["intangibles"].get(fy, (None,))[0]

        put("revenue", p, rev)
        put("net_income", p, ni)
        put("operating_income", p, ebit)
        put("tax", p, abs(tax) if tax is not None else None)
        put("ocf", p, ocf)
        # capex: EDGAR lo reporta POSITIVO (salida de efectivo); el driver espera signo EODHD (negativo)
        put("capex", p, -abs(capex) if capex is not None else None)
        # D&A OPERATIVA = D&A total − amortización de adquisiciones (si ambas; si no, D&A total)
        dna_op = None
        if dna_total is not None:
            dna_op = dna_total - abs(amort) if amort is not None else dna_total
        put("dna", p, dna_op)
        put("cash", p, cash)

        # deuda total = LongTermDebt (incluye porción corriente) si existe; si no, no corriente + corriente + corto
        if d_lt_total is not None:
            total_debt = d_lt_total + (d_short or 0.0)
        else:
            total_debt = (d_lt_nc or 0.0) + (d_cur or 0.0) + (d_short or 0.0)
            if d_lt_nc is None and d_cur is None and d_short is None:
                total_debt = None
        put("total_debt", p, total_debt)

        # acciones: preferir promedio ponderado diluido (consistente con EPS); si no, en circulación
        put("shares", p, sh_w if sh_w is not None else sh_o)
        put("equity", p, equity)

        # CAPITAL INVERTIDO real = equity + deuda total − caja (operativo). Requiere equity y deuda.
        inv_cap = None
        if equity is not None and total_debt is not None:
            inv_cap = equity + total_debt - (cash or 0.0)
        put("invested_capital", p, inv_cap)

        # ΔWC a partir de (activo corriente − pasivo corriente); signo consistente con reinversión (+ = uso de caja)
        wc = (ac - lc) if (ac is not None and lc is not None) else None
        if wc is not None and prev_wc is not None:
            put("wc_change", p, wc - prev_wc)
        if wc is not None:
            prev_wc = wc

        meta[p] = {"dna_total": dna_total, "amort_acq": (abs(amort) if amort is not None else None),
                   "goodwill": gw, "intangibles": intang, "pretax": flow["pretax"].get(fy, (None,))[0],
                   "equity": equity, "total_debt": total_debt, "cash": cash}

    return {"currency": ccy, "by_field": by, "meta": meta}


def fetch_edgar_rows(writer, ticker: str) -> List[dict]:
    """Lee las filas fundamentals_pit de un ticker desde Supabase (todas las columnas necesarias)."""
    cols = "concept,period_start,period_end,value,filing_date,unit,taxonomy,fiscal_period,accession"
    return writer.select_rows("fundamentals_pit", select=cols,
                              params={"ticker": f"eq.{ticker.upper()}", "order": "period_end"})
