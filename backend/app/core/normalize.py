"""Capa de NORMALIZACIÓN financiera (independiente del conector).

Extraída de `providers/edgar.py` (E1) SIN cambiar la lógica: mapas de conceptos canónicos
US-GAAP / IFRS y helpers puros de período, duración, TTM por identidad rodante y selección de
concepto. No depende de pandas ni de red; es reutilizable por cualquier conector que entregue
hechos en el formato companyfacts (taxonomía → concepto → units → filas start/end/val/filed/form).

Garantía E1: las funciones son idénticas a las que vivían en edgar.py (diff-0 en resultados).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional, Tuple


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# Formularios anuales: 10-K (US), 20-F / 40-F (emisores extranjeros). Más enmiendas (/A).
ANNUAL_FORMS = ("10-K", "20-F", "40-F")

# Conceptos por taxonomía. us-gaap (emisores domésticos) e ifrs-full (20-F).
US_GAAP_MAP = {
    "rev": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenuesNetOfInterestExpense"],
    "ni": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "equity": ["StockholdersEquity"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PaymentsToAcquireOtherPropertyPlantAndEquipment", "PaymentsForCapitalImprovements",
              "PaymentsToAcquireMachineryAndEquipment"],
    "wdil": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "wbas": ["WeightedAverageNumberOfSharesOutstandingBasic", "WeightedAverageNumberOfShareOutstandingBasicAndDiluted"],
    "gross_profit": ["GrossProfit"],
    "op_income": ["OperatingIncomeLoss"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsAndShortTermInvestments",
             "CashAndCashEquivalentsAndShortTermInvestments"],
    "sti": ["ShortTermInvestments"],
    "debt_lt": ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"],
    "debt_cur": ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings",
                 "LongTermDebtAndCapitalLeaseObligationsCurrent", "ShortTermBorrowingsAndCurrentPortionOfLongTermDebt"],
    "debt_combined": ["DebtLongtermAndShorttermCombinedAmount"],
    "capex_alt": ["PaymentsToAcquireProductiveAssets", "PaymentsForProceedsFromProductiveAssets",
                  "PaymentsToAcquireOtherProductiveAssets", "PaymentsForCapitalImprovements"],
}
IFRS_MAP = {
    "rev": ["RevenueFromContractsWithCustomers", "Revenue"],
    "ni": ["ProfitLoss", "ProfitLossAttributableToOwnersOfParent"],
    "eps": ["DilutedEarningsLossPerShare", "BasicEarningsLossPerShare",
            "DilutedEarningsPerShare", "BasicEarningsPerShare"],
    "equity": ["Equity", "EquityAttributableToOwnersOfParent"],
    "ocf": ["CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "wdil": ["WeightedAverageShares", "AdjustedWeightedAverageShares"],
    "wbas": ["WeightedAverageShares"],
    "gross_profit": ["GrossProfit"],
    "op_income": ["ProfitLossFromOperatingActivities", "OperatingIncomeLoss"],
    "cash": ["CashAndCashEquivalents"],
    "sti": ["ShorttermInvestments", "CurrentInvestments"],
    "debt_lt": ["NoncurrentPortionOfNoncurrentBorrowings", "NoncurrentBorrowings", "Borrowings"],
    "debt_cur": ["CurrentBorrowings", "ShorttermBorrowings"],
    "debt_combined": ["Borrowings"],
    "capex_alt": ["PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillAndInvestmentProperty"],
}


def _at(points: List[Tuple[date, float]], ref: Optional[date], tol_days: int = 20) -> Optional[float]:
    """Valor cuyo fin coincide con el período de referencia (±tol). Evita MEZCLAR períodos
    (p. ej. tomar la utilidad neta de 2013 con el EPS de 2025). None si no hay en ese período."""
    if not points or ref is None:
        return None
    best = None
    for d, v in points:
        gap = abs((d - ref).days)
        if gap <= tol_days and (best is None or gap < best[0]):
            best = (gap, v)
    return best[1] if best else None


def _concept_at(facts, taxonomy, names, unit, ref) -> Tuple[Optional[float], Optional[str]]:
    """Primer concepto de la lista con valor ANUAL en el período de referencia → (valor, concepto).
    Permite registrar la PROCEDENCIA exacta de la utilidad neta reportada (no reconstruida)."""
    for n in names:
        v = _at(_annual_points(_concept(facts, taxonomy, n, unit)), ref)
        if v is not None:
            return v, n
    return None, None


# --- EPS TTM a prueba de splits (Control 2) ---------------------------------------
# El EPS por acción NO es sumable entre trimestres con bases de acciones distintas (p. ej.
# antes/después de un split 10:1). La forma correcta y split-INVARIANTE es sumar la UTILIDAD
# NETA trimestral (montos absolutos, invariantes al split) de 4 trimestres de 3 MESES (no YTD)
# y dividir por las acciones diluidas VIGENTES. Así el split no contamina el resultado.
def quarterly_3m_points(unit_rows: list) -> List[Tuple[date, date, float, date]]:
    """Puntos TRIMESTRALES de 3 meses (start,end,val,filed); filed más reciente gana por período."""
    out = {}
    for r in unit_rows or []:
        s, e, v = _parse_date(r.get("start")), _parse_date(r.get("end")), r.get("val")
        if v is None or not s or not e:
            continue
        if 80 <= (e - s).days <= 100:
            filed = _parse_date(r.get("filed")) or date.min
            if e not in out or filed >= out[e][3]:
                out[e] = (s, e, float(v), filed)
    return [out[k][:3] + (out[k][3],) for k in sorted(out)]


def eps_ttm_from_quarterly_ni(ni_3m_points: List[Tuple[date, date, float, date]],
                              diluted_shares: Optional[float], n: int = 4) -> Optional[dict]:
    """EPS TTM split-invariante = Σ(utilidad neta de los últimos 4 trimestres de 3m) / acciones
    diluidas vigentes. Exige 4 trimestres CONSECUTIVOS y sin solapamiento (no YTD). None si faltan."""
    if not ni_3m_points or not diluted_shares or diluted_shares <= 0 or len(ni_3m_points) < n:
        return None
    last = ni_3m_points[-n:]
    # sin solapamiento: cada inicio ~ fin del anterior (trimestres contiguos)
    for i in range(1, len(last)):
        gap = (last[i][0] - last[i - 1][1]).days
        if gap > 10:            # hueco entre trimestres -> serie incompleta
            return None
    ni_ttm = sum(p[2] for p in last)
    return {"eps_ttm": ni_ttm / diluted_shares, "ni_ttm": ni_ttm,
            "start": last[0][0].isoformat(), "end": last[-1][1].isoformat(), "n_quarters": n}


def detect_eps_split_mixing(eps_quarterly_points: List[Tuple[date, float]],
                            split_dates: List[date]) -> bool:
    """True si una serie de EPS POR ACCIÓN trimestral cruza una fecha de split (bases no homogéneas).
    Señala que NO se deben sumar esos EPS por acción directamente."""
    if not eps_quarterly_points or not split_dates:
        return False
    ends = [d for d, _ in eps_quarterly_points]
    lo, hi = min(ends), max(ends)
    return any(lo < sd <= hi for sd in split_dates)


def _q3m(facts, taxonomy, names, unit) -> List[Tuple[date, date, float, date]]:
    """Mejor serie TRIMESTRAL de 3 meses (variante de concepto con más puntos recientes)."""
    best: List[Tuple[date, date, float, date]] = []
    for n in names:
        pts = quarterly_3m_points(_concept(facts, taxonomy, n, unit))
        if pts and (not best or pts[-1][1] > best[-1][1] or len(pts) > len(best)):
            best = pts
    return best


def _sum_last4_3m(qpts: List[Tuple[date, date, float, date]]) -> Optional[Tuple[float, date, date]]:
    """Suma de 4 trimestres de 3m CONSECUTIVOS (sin YTD, sin huecos). None si no hay 4 contiguos."""
    if not qpts or len(qpts) < 4:
        return None
    last = qpts[-4:]
    for i in range(1, 4):
        if (last[i][0] - last[i - 1][1]).days > 10:      # hueco entre trimestres
            return None
    return sum(p[2] for p in last), last[0][0], last[-1][1]


def _duration_rows(unit_rows: list) -> List[Tuple[date, date, float, int, date]]:
    """(start,end,val,días,filed) de hechos de DURACIÓN, con filed más reciente por (start,end)."""
    out = {}
    for r in unit_rows or []:
        s, e, v = _parse_date(r.get("start")), _parse_date(r.get("end")), r.get("val")
        if v is None or not s or not e:
            continue
        days = (e - s).days
        if days < 60:
            continue
        filed = _parse_date(r.get("filed")) or date.min
        k = (s, e)
        if k not in out or filed >= out[k][4]:
            out[k] = (s, e, float(v), days, filed)
    return sorted(out.values(), key=lambda x: x[1])


def ttm_flow(unit_rows: list) -> Optional[dict]:
    """TTM de un FLUJO (utilidad, EPS por acción, OCF, CAPEX) por la identidad rodante:
    TTM = acumulado del ejercicio en curso + ejercicio anterior completo − acumulado del año
    anterior al mismo corte. Usa YTD + anual (etiquetas fiables), NO exige 4 trimestres sueltos,
    y es consistente ante splits porque usa los COMPARATIVOS REEXPRESADOS (filed más reciente).
    Si el último dato es el anual, TTM = anual (equivale al ejercicio)."""
    dur = _duration_rows(unit_rows)
    if not dur:
        return None
    annual = [(s, e, v) for (s, e, v, d, _f) in dur if 330 <= d <= 400]
    interim = [(s, e, v, d) for (s, e, v, d, _f) in dur if 60 <= d <= 300]
    if not annual:
        return None
    latest_annual = max(annual, key=lambda x: x[1])
    latest_interim = max(interim, key=lambda x: x[1]) if interim else None
    # Sin interino más reciente que el anual → TTM = anual (ejercicio completo).
    if latest_interim is None or latest_interim[1] <= latest_annual[1]:
        return {"ttm": latest_annual[2], "end": latest_annual[1].isoformat(), "window": "anual"}
    s, e, y, L = latest_interim
    import datetime as _dt
    prior_annual = [a for a in annual if abs((a[1] - (s - _dt.timedelta(days=1))).days) <= 45]
    prior_ytd = [it for it in interim if abs((it[1] - (e - _dt.timedelta(days=365))).days) <= 25
                 and abs(it[3] - L) <= 25]
    if prior_annual and prior_ytd:
        ttm = y + prior_annual[0][2] - prior_ytd[0][2]
        return {"ttm": ttm, "end": e.isoformat(), "window": f"YTD({L}d)+anual−YTD_prev"}
    # Sin comparativos para cerrar la identidad: no se fabrica un TTM parcial.
    return {"ttm": latest_annual[2], "end": latest_annual[1].isoformat(), "window": "anual(sin_comparativos_TTM)"}


def _ttm_best(facts, taxonomy, names, unit) -> Optional[dict]:
    """TTM del mejor concepto-variante disponible (el de corte más reciente)."""
    best = None
    for n in names:
        t = ttm_flow(_concept(facts, taxonomy, n, unit))
        if t and (best is None or t["end"] > best["end"]):
            best = t
    return best


def _latest_dur(facts, taxonomy, names, unit) -> Optional[Tuple[date, float]]:
    """Valor de DURACIÓN (p. ej. acciones ponderadas diluidas) con la fecha de corte más reciente,
    entre variantes de concepto. Sirve de denominador diluido CONSISTENTE y reciente para EPS TTM."""
    best = None
    for n in names:
        for (s, e, v, _d, _f) in _duration_rows(_concept(facts, taxonomy, n, unit)):
            if best is None or e > best[0]:
                best = (e, v)
    return best


def _annual_points(unit_rows: list, forms: Tuple[str, ...] = ANNUAL_FORMS) -> List[Tuple[date, float]]:
    """Valores anuales (duración ~365d, formulario anual) ordenados por fecha fin.

    Dedup por fecha fin con GANA EL DE PRESENTACIÓN MÁS RECIENTE (filed), para que un
    valor REEXPRESADO (p. ej. EPS post-split de Netflix) sustituya al original. Si no hay
    filed, gana el último en orden de aparición.
    """
    out = {}  # end_date -> (val, filed)
    for r in unit_rows or []:
        start, end, val, form = r.get("start"), r.get("end"), r.get("val"), str(r.get("form", ""))
        if val is None or not start or not end or not any(form.startswith(p) for p in forms):
            continue
        d0, d1 = _parse_date(start), _parse_date(end)
        if not d0 or not d1:
            continue
        if 330 <= (d1 - d0).days <= 400:        # ~1 año fiscal
            filed = _parse_date(r.get("filed")) or date.min
            if d1 not in out or filed >= out[d1][1]:
                out[d1] = (float(val), filed)
    return sorted((d, v) for d, (v, _f) in out.items())


def _instant_points(unit_rows: list, forms: Tuple[str, ...] = ANNUAL_FORMS) -> List[Tuple[date, float]]:
    """Valores de balance (instantáneos) de formularios anuales; filed más reciente gana."""
    out = {}  # end_date -> (val, filed)
    for r in unit_rows or []:
        end, val, form = r.get("end"), r.get("val"), str(r.get("form", ""))
        if val is None or not end or not any(form.startswith(p) for p in forms):
            continue
        d = _parse_date(end)
        if not d:
            continue
        filed = _parse_date(r.get("filed")) or date.min
        if d not in out or filed >= out[d][1]:
            out[d] = (float(val), filed)
    return sorted((d, v) for d, (v, _f) in out.items())


def _concept(facts: dict, taxonomy: str, name: str, unit: str) -> list:
    try:
        return facts["facts"][taxonomy][name]["units"][unit]
    except (KeyError, TypeError):
        return []


def _first_concept(facts, taxonomy, names, unit):
    for n in names:
        rows = _concept(facts, taxonomy, n, unit)
        if rows:
            return rows
    return []


def _best_annual(facts, taxonomy, names, unit) -> List[Tuple[date, float]]:
    """Entre variantes de concepto, usa la que tenga datos ANUALES más RECIENTES.

    Evita series obsoletas cuando el emisor migró de etiqueta (p. ej. META:
    'Revenues' hasta 2017 vs 'RevenueFromContractWithCustomerExcludingAssessedTax').
    """
    best: List[Tuple[date, float]] = []
    for n in names:
        pts = _annual_points(_concept(facts, taxonomy, n, unit))
        if pts and (not best or pts[-1][0] > best[-1][0]):
            best = pts
    return best


def _best_instant(facts, taxonomy, names, unit) -> List[Tuple[date, float]]:
    best: List[Tuple[date, float]] = []
    for n in names:
        pts = _instant_points(_concept(facts, taxonomy, n, unit))
        if pts and (not best or pts[-1][0] > best[-1][0]):
            best = pts
    return best


def _currency_for(facts, taxonomy, names) -> Optional[str]:
    """Divisa de reporte: primera unidad monetaria (3 letras, sin '/') con datos."""
    try:
        node = facts["facts"][taxonomy]
    except (KeyError, TypeError):
        return None
    for n in names:
        units = (node.get(n, {}) or {}).get("units", {}) or {}
        for u in units:
            if "/" not in u and len(u) == 3 and u.isalpha():
                return u.upper()
    return None
