"""Conector SEC EDGAR (data.sec.gov) — fundamentales OFICIALES y GRATIS (US).

Fuente: XBRL company facts de las propias presentaciones a la SEC. Sin clave; exige
un User-Agent con contacto (política de la SEC). Cobertura: emisores estadounidenses.
Lo que no está en las presentaciones NO se inventa: queda en None.

Campos derivados de EDGAR: net_margin, roe, rev_growth_yoy, eps_growth_yoy, fcf_yield
(si hay precio y acciones), market_cap (precio × acciones), pe_ttm (precio / EPS).
No disponibles de forma fiable y gratuita aquí: pe_forward, ev_ebitda, roic => None
(documentado). El parser `parse_companyfacts` es puro y se prueba con fixtures.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple


from ..core.types import ETFHolding, Fundamentals, Instrument, Quote
from .base import MarketDataProvider

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# Formularios anuales: 10-K (US), 20-F / 40-F (emisores extranjeros). Más enmiendas (/A).
ANNUAL_FORMS = ("10-K", "20-F", "40-F")

# Conceptos por taxonomía. us-gaap (emisores domésticos) e ifrs-full (20-F).
US_GAAP_MAP = {
    "rev": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "ni": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "equity": ["StockholdersEquity"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
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
# ADR: 1 ADR = N acciones ordinarias (hechos verificables, no estimaciones).
ADR_RATIO = {"TSM": 5.0, "ASML": 1.0}


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


def parse_companyfacts(facts: dict, ticker: str,
                       price: Optional[float] = None,
                       shares: Optional[float] = None,
                       fx_map: Optional[Dict[str, float]] = None,
                       adr_ratio: Optional[float] = None,
                       fallback: Optional[dict] = None) -> Fundamentals:
    """Construye Fundamentals desde company facts de EDGAR. Campos ausentes => None.

    Cubre us-gaap (USD) e ifrs-full (emisores 20-F; divisa detectada, p. ej. EUR/TWD).
    - Ratios adimensionales (margen, ROE, crecimientos) son correctos en cualquier divisa.
    - pe_ttm / fcf_yield / market_cap mezclan precio en USD con cifras en divisa de reporte:
      se convierten con `fx_map` (USD por 1 unidad de divisa) y el `adr_ratio` (acciones
      ordinarias por ADR). Sin FX disponible para una divisa != USD => quedan en None
      (no se fabrican).
    """
    fx_map = fx_map or {}

    # Taxonomía + DIVISA DE REPORTE, data-driven. Muchos emisores extranjeros usan
    # etiquetas us-gaap pero en su divisa (ASML: us-gaap en EUR, formulario 20-F);
    # otros usan ifrs-full (TSM: TWD). Se detecta la divisa DENTRO de cada taxonomía
    # (no se asume USD) y se elige la que produzca datos anuales reales.
    def _pick(tax_name, cmap):
        c = _currency_for(facts, tax_name, cmap["rev"] + cmap["ni"] + cmap["equity"])
        if not c:
            return None
        r = _best_annual(facts, tax_name, cmap["rev"], c)
        n = _best_annual(facts, tax_name, cmap["ni"], c)
        if not (r or n):
            return None
        return (tax_name, c, cmap, r, n)

    picked = _pick("us-gaap", US_GAAP_MAP) or _pick("ifrs-full", IFRS_MAP)
    if picked:
        tax, ccy, M, rev, ni = picked
    else:
        tax, ccy, M, rev, ni = "us-gaap", "USD", US_GAAP_MAP, [], []

    eps = _best_annual(facts, tax, M["eps"], f"{ccy}/shares")
    # EPS oficial en USD por acción (p. ej. TSM publica DilutedEarningsLossPerShare en
    # USD/shares además de TWD): se prefiere para el P/E y se evita convertir desde la
    # divisa local. Es por ACCIÓN ORDINARIA; el factor ADR se aplica una sola vez abajo.
    eps_usd_series = _best_annual(facts, tax, M["eps"], "USD/shares") if ccy != "USD" else []
    equity = _best_instant(facts, tax, M["equity"], ccy)
    ocf = _best_annual(facts, tax, M["ocf"], ccy)
    capex = _best_annual(facts, tax, M["capex"], ccy)
    wdil = _best_annual(facts, tax, M.get("wdil", []), "shares")   # acciones promedio diluidas
    # Acciones VIGENTES (para market cap): portada dei; si está obsoleta, se marca abajo.
    entity_sh_pts = _best_instant(facts, "dei", ["EntityCommonStockSharesOutstanding"], "shares") or \
        _best_instant(facts, tax, ["CommonStockSharesOutstanding"], "shares")

    def yoy(points):
        if len(points) < 2 or points[-2][1] in (0, None):
            return None
        prev = points[-2][1]
        if prev == 0:
            return None
        return points[-1][1] / prev - 1.0

    # PERÍODO DE REFERENCIA: ancla en el EPS diluido reciente (el dato mejor etiquetado).
    # Todos los flujos se toman EN ESE período (evita mezclar p. ej. NI 2013 con EPS 2025).
    ref = (eps[-1][0] if eps else (eps_usd_series[-1][0] if eps_usd_series
           else (ni[-1][0] if ni else (rev[-1][0] if rev else None))))
    eps_l = _at(eps, ref)
    rev_l = _at(rev, ref)
    eq_l = _at(equity, ref)
    ocf_l = _at(ocf, ref)
    capex_l = _at(capex, ref)
    wdil_l = _at(wdil, ref)

    # Utilidad neta REPORTADA en el período de referencia, con su CONCEPTO fuente (independiente
    # del EPS). Se busca el concepto correcto (no sólo NetIncomeLoss). Si NINGÚN concepto directo
    # existe en ese período (p. ej. MA dejó de etiquetarlo), se RECONSTRUYE = EPS×acciones diluidas
    # — pero ESO NO es una validación independiente y se marca como tal.
    ni_direct, ni_source_concept = _concept_at(facts, tax, M["ni"], ccy, ref)
    ni_reconstructed = False
    ni_l = ni_direct
    ni_period = ref.isoformat() if (ni_direct is not None and ref) else None
    if ni_l is None and eps_l is not None and wdil_l:
        ni_l = eps_l * wdil_l
        ni_reconstructed = True
        ni_source_concept = "reconstruido: EPS_diluido × acciones_ponderadas_diluidas"
        ni_period = ref.isoformat() if ref else None
    as_of = ref.isoformat() if ref else None

    # Consistencia INDEPENDIENTE: SÓLO cuando la utilidad neta es REPORTADA (no reconstruida) y hay
    # acciones ponderadas diluidas → se comparan DOS hechos EDGAR independientes (NI reportado vs
    # EPS×acciones). Si el NI es reconstruido, NO se declara consistencia (sería circular).
    eps_consistent = None
    eps_check_ratio = None
    consistency_independent = False
    if (not ni_reconstructed) and eps_l is not None and wdil_l and ni_direct not in (None, 0):
        eps_check_ratio = (eps_l * wdil_l) / ni_direct
        eps_consistent = abs(eps_check_ratio - 1.0) <= 0.15
        consistency_independent = True

    # Adimensionales (válidos en cualquier divisa) SOLO si numerador/denominador son del mismo período.
    net_margin = (ni_l / rev_l) if (ni_l is not None and rev_l) else None
    roe = (ni_l / eq_l) if (ni_l is not None and eq_l) else None

    # GUARD DE PLAUSIBILIDAD (Control 2): detecta magnitudes imposibles (p. ej. MU FY2026 con NI
    # mayor que los ingresos). Marca el dato y evita que se use a ciegas en valoración.
    eg_raw = yoy(eps)
    rg_raw = yoy(rev)
    data_quality, quality_reason = "ok", None
    if ni_l is not None and rev_l and ni_l > rev_l:
        data_quality = "bloqueado"
        quality_reason = f"utilidad neta ({ni_l:.4g}) > ingresos ({rev_l:.4g}) — magnitud imposible; verificar documento original"
    elif eg_raw is not None and abs(eg_raw) > 3.0:
        data_quality = "bloqueado"
        quality_reason = (f"salto de EPS interanual {eg_raw*100:.0f}% implausible"
                          + (f" (ingresos {rg_raw*100:.0f}% con multiplicador distinto → probable error de origen)" if rg_raw is not None else "")
                          + "; verificar 10-K original antes de usar")
    elif net_margin is not None and net_margin > 0.6:
        data_quality = "sospechoso"
        quality_reason = f"margen neto {net_margin*100:.0f}% inusualmente alto; posible dato extraordinario o erróneo (verificar sector)"
    elif eg_raw is not None and abs(eg_raw) > 1.5:
        data_quality = "sospechoso"
        quality_reason = f"salto de EPS interanual {eg_raw*100:.0f}% — posible ciclicidad extrema o error; verificar"

    # Acciones vigentes para market cap: portada si es reciente; si es obsoleta (>400d que la
    # referencia) se usa el promedio diluido reciente como proxy (marcado); si no, lo que haya.
    shares_source = None
    if shares is None:
        entity_last_end = entity_sh_pts[-1][0] if entity_sh_pts else None
        entity_val = entity_sh_pts[-1][1] if entity_sh_pts else None
        stale_entity = (entity_last_end is not None and ref is not None
                        and (ref - entity_last_end).days > 400)
        if entity_val is not None and not stale_entity:
            shares, shares_source = entity_val, "dei_entity_coverpage"
        elif wdil_l:
            shares, shares_source = wdil_l, "weighted_diluted_proxy(portada_obsoleta)"
        elif entity_val is not None:
            shares, shares_source = entity_val, "dei_entity_coverpage(obsoleta)"
    else:
        shares_source = "provided"

    adr = adr_ratio if adr_ratio else 1.0
    fx = 1.0 if ccy == "USD" else fx_map.get(ccy)      # USD por 1 unidad de la divisa
    # EPS por ADR en USD: preferir la cifra oficial en USD/shares (conv=1); si no, convertir
    # la local con FX. En ambos casos × adr una sola vez (acción ordinaria -> ADR).
    # EPS ANUAL (EDGAR) en USD por ADR.
    if eps_usd_series:
        eps_for_pe, eps_conv = _at(eps_usd_series, ref) or eps_usd_series[-1][1], 1.0
    else:
        eps_for_pe, eps_conv = eps_l, fx
    eps_annual_usd = (eps_for_pe * adr * eps_conv) if (eps_for_pe is not None and eps_conv) else None

    # EPS TTM — Control C (rigor). La identidad rodante (YTD + anual − YTD previo) se aplica a una
    # MAGNITUD ACUMULATIVA: la UTILIDAD NETA. El EPS por acción NO es aditivo si cambia la base de
    # acciones, así que se divide NI_TTM entre acciones ponderadas diluidas RECIENTES (denominador
    # consistente, no "último trimestre a secas") y se CONTRASTA con la identidad por-acción.
    eps_ttm_usd = eps_ttm_method = eps_ttm_window = None
    eps_ttm_denominator = eps_ttm_pershare_check = None
    ni_ttm = _ttm_best(facts, tax, M["ni"], ccy)
    wdil_den = _latest_dur(facts, tax, M.get("wdil", []), "shares")
    if ni_ttm is not None and "YTD" in ni_ttm["window"] and wdil_den and wdil_den[1] > 0:
        conv = 1.0 if ccy == "USD" else (fx or 0)
        if conv:
            eps_ttm_usd = (ni_ttm["ttm"] / wdil_den[1]) * adr * conv or None
            eps_ttm_method = "utilidad_neta_TTM / acciones_diluidas"
            eps_ttm_window = ni_ttm["window"]
            eps_ttm_denominator = wdil_den[1]
            # Contraste con la identidad POR ACCIÓN (sólo informativo): ≈1 si la base de acciones
            # fue comparable; divergencia → cambio de base (recompras/emisión) → prevalece NI/acciones.
            ps = (_ttm_best(facts, tax, M["eps"], "USD/shares") if ccy != "USD" else None) \
                or _ttm_best(facts, tax, M["eps"], f"{ccy}/shares")
            if eps_ttm_usd and ps and "YTD" in ps["window"]:
                ps_is_usd = (ccy == "USD") or bool(_ttm_best(facts, tax, M["eps"], "USD/shares"))
                ps_usd = ps["ttm"] * adr * (1.0 if ps_is_usd else (fx or 1))
                if ps_usd:
                    eps_ttm_pershare_check = round(eps_ttm_usd / ps_usd, 4)
    ttm_vs_annual_ratio = (eps_ttm_usd / eps_annual_usd) if (eps_ttm_usd and eps_annual_usd) else None

    # EPS primario: TTM si está disponible (más actual); si no, el anual. El fallback (abajo) sólo
    # actúa si no hay ninguno de EDGAR.
    if eps_ttm_usd is not None:
        eps_usd, eps_source, eps_basis = eps_ttm_usd, "edgar", "ttm"
    elif eps_annual_usd is not None:
        eps_usd, eps_source, eps_basis = eps_annual_usd, "edgar", "reported_annual"
    else:
        eps_usd = eps_source = eps_basis = None

    # --- FALLBACK MULTIFUENTE CONTROLADO (p. ej. Yahoo) ---
    # SÓLO cuando EDGAR no da el dato; NUNCA sobrescribe un dato oficial; exige coherencia de
    # moneda (USD, el ADR/acción cotiza en USD) y precio; registra fuente/fecha/base; no inventa
    # si el fallback tampoco tiene cobertura. El EPS de Yahoo (trailingEps) es TTM por ADR/acción.
    def _fin(x):
        return isinstance(x, (int, float)) and x == x and x not in (float("inf"), float("-inf"))
    fb = fallback or {}
    fallback_sources: List[str] = []
    if eps_usd is None and price:
        fe, fc = fb.get("eps_ttm"), (fb.get("currency") or "").upper()
        if _fin(fe) and fe > 0 and fc in ("", "USD"):
            eps_usd, eps_source, eps_basis = float(fe), (fb.get("source") or "fallback"), "ttm"
            fallback_sources.append(f"eps_ttm<-{eps_source}@{fb.get('as_of')}")
    if (shares is None or (shares_source and "obsoleta" in shares_source)) and _fin(fb.get("shares")) and fb["shares"] > 0:
        shares = float(fb["shares"])
        shares_source = (fb.get("source") or "fallback") + ":shares"
        fallback_sources.append(f"shares<-{fb.get('source')}@{fb.get('as_of')}")

    adr_count = (shares / adr) if shares else None
    market_cap = (price * adr_count) if (price and adr_count) else None

    # FCF anual y TTM (Control D). FCF = flujo operativo − CAPEX (verificado por etiqueta).
    capex_l = capex_l if capex_l is not None else _at(_best_annual(facts, tax, M.get("capex_alt", []), ccy), ref)
    fcf_annual_ccy = (ocf_l - capex_l) if (ocf_l is not None and capex_l is not None) else None
    ocf_ttm = _ttm_best(facts, tax, M["ocf"], ccy)
    capex_ttm = _ttm_best(facts, tax, M["capex"], ccy) or _ttm_best(facts, tax, M.get("capex_alt", []), ccy)
    # TTM sólo si AMBOS son TTM reales (misma identidad rodante), para no mezclar anual con TTM.
    fcf_ttm_ccy = (ocf_ttm["ttm"] - capex_ttm["ttm"]) if (
        ocf_ttm and capex_ttm and "YTD" in ocf_ttm["window"] and "YTD" in capex_ttm["window"]) else None
    fcf_annual = (fcf_annual_ccy * fx) if (fcf_annual_ccy is not None and fx) else None   # USD
    fcf_ttm = (fcf_ttm_ccy * fx) if (fcf_ttm_ccy is not None and fx) else None             # USD
    fcf_for_yield = fcf_ttm if fcf_ttm is not None else fcf_annual
    fcf_yield = (fcf_for_yield / market_cap) if (fcf_for_yield is not None and market_cap) else None
    pe_ttm = (price / eps_usd) if (price and eps_usd and eps_usd > 0) else None

    # Deuda (Control D): bruta = corto + largo plazo; neta = bruta − efectivo. En divisa de reporte
    # (ver `currency`); se distingue explícitamente bruta/efectivo/neta y se omite si falta.
    debt_lt = _at(_best_instant(facts, tax, M.get("debt_lt", []), ccy), ref)
    debt_cur = _at(_best_instant(facts, tax, M.get("debt_cur", []), ccy), ref)
    debt_combined = _at(_best_instant(facts, tax, M.get("debt_combined", []), ccy), ref)
    if debt_lt is not None or debt_cur is not None:
        gross_debt = (debt_lt or 0.0) + (debt_cur or 0.0)
    elif debt_combined is not None:
        gross_debt = debt_combined
    else:
        gross_debt = None
    cash_and_sti = _at(_best_instant(facts, tax, M.get("cash", []), ccy), ref)   # efectivo y equivalentes (o combinado)
    net_debt = (gross_debt - cash_and_sti) if (gross_debt is not None and cash_and_sti is not None) else None

    # Márgenes adicionales (mismo período de referencia).
    gp = _at(_best_annual(facts, tax, M.get("gross_profit", []), ccy), ref)
    opi = _at(_best_annual(facts, tax, M.get("op_income", []), ccy), ref)
    gross_margin = (gp / rev_l) if (gp is not None and rev_l) else None
    operating_margin = (opi / rev_l) if (opi is not None and rev_l) else None
    diluted_shares = wdil_l

    return Fundamentals(
        ticker=ticker,
        pe_ttm=pe_ttm,
        eps=eps_usd,                # EPS (USD por ADR): EDGAR anual o fallback TTM (ver eps_source)
        eps_basis=eps_basis,        # reported_annual (EDGAR) | ttm (fallback) | None
        eps_source=eps_source,      # edgar | yahoo:quote | ... (procedencia del EPS)
        fallback_sources=(", ".join(fallback_sources) or None),
        eps_consistent=eps_consistent,
        eps_check_ratio=(round(eps_check_ratio, 4) if eps_check_ratio is not None else None),
        consistency_independent=consistency_independent,
        ni_reconstructed=ni_reconstructed,
        ni_source_concept=ni_source_concept,
        ni_period=ni_period,
        shares_source=shares_source,
        eps_annual=eps_annual_usd,
        eps_ttm=eps_ttm_usd,
        eps_ttm_method=eps_ttm_method,
        eps_ttm_window=eps_ttm_window,
        ttm_vs_annual_ratio=(round(ttm_vs_annual_ratio, 4) if ttm_vs_annual_ratio is not None else None),
        fcf_annual=fcf_annual,
        fcf_ttm=fcf_ttm,
        diluted_shares=diluted_shares,
        gross_debt=gross_debt,
        cash_and_sti=cash_and_sti,
        net_debt=net_debt,
        gross_margin=gross_margin,
        operating_margin=operating_margin,
        eps_ttm_denominator=eps_ttm_denominator,
        eps_ttm_pershare_check=eps_ttm_pershare_check,
        data_quality=data_quality,
        quality_reason=quality_reason,
        pe_forward=None,            # no disponible gratis en EDGAR
        ev_ebitda=None,             # requiere deuda/caja + EBITDA fiables
        fcf_yield=fcf_yield,
        roic=None,                  # no derivado aquí
        roe=roe,
        rev_growth_yoy=yoy(rev),
        eps_growth_yoy=yoy(eps),
        net_margin=net_margin,
        debt_to_equity=None,
        market_cap=market_cap,
        currency=ccy,
        as_of=as_of,
        taxonomy=tax,
        is_sample=False,
    )


class EDGARProvider(MarketDataProvider):
    name = "edgar"
    is_sample = False

    def __init__(self, user_agent: str, timeout: float = 15.0, retries: int = 2):
        if not user_agent or "@" not in user_agent:
            raise ValueError("EDGAR exige User-Agent con email de contacto (política SEC).")
        import httpx
        self.retries = retries
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": user_agent})
        self._cik: Dict[str, int] = {}

    def _fetch(self, url: str):
        """GET con un reintento ante timeout/red transitoria."""
        last = None
        for _ in range(max(1, self.retries)):
            try:
                return self._client.get(url)
            except Exception as e:
                last = e
        raise last

    def _load_ciks(self):
        if self._cik:
            return
        r = self._fetch(TICKERS_URL)
        r.raise_for_status()
        for row in r.json().values():
            self._cik[row["ticker"].upper()] = int(row["cik_str"])

    def _facts(self, ticker: str) -> Optional[dict]:
        self._load_ciks()
        cik = self._cik.get(ticker.upper())
        if cik is None:
            return None
        r = self._fetch(FACTS_URL.format(cik=cik))
        if r.status_code != 200:
            return None
        return r.json()

    def get_fundamentals(self, tickers: List[str], prices: Optional[Dict[str, float]] = None,
                         fx_map: Optional[Dict[str, float]] = None,
                         fallback_stats: Optional[Dict[str, dict]] = None) -> Dict[str, Fundamentals]:
        prices = prices or {}
        fx_map = fx_map or {}
        fallback_stats = fallback_stats or {}
        out = {}
        for t in tickers:
            facts = self._facts(t)
            if facts is None:
                continue
            out[t] = parse_companyfacts(facts, t, price=prices.get(t), fx_map=fx_map,
                                        adr_ratio=ADR_RATIO.get(t.upper(), 1.0),
                                        fallback=fallback_stats.get(t.upper()) or fallback_stats.get(t))
        return out

    # EDGAR no da precios/FX/holdings
    def get_quotes(self, tickers: List[str]) -> Dict[str, Quote]:
        return {}

    def get_price_history(self, ticker, start=None, end=None):
        import pandas as pd        # perezoso: el parser puro (parse_companyfacts) no requiere pandas
        return pd.Series(dtype=float)

    def get_etf_holdings(self, etf_ticker: str) -> List[ETFHolding]:
        return []

    def list_universe(self, exchanges=None, limit=None) -> List[Instrument]:
        return []

    def health(self) -> dict:
        return {"provider": self.name, "is_sample": False, "ok": True,
                "coverage": "Fundamentales oficiales US (SEC EDGAR); sin pe_forward/ev_ebitda/roic"}
