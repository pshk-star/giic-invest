"""Enriquecimiento de fundamentales con EODHD sobre el ancla oficial EDGAR.

ÚNICA implementación de las reglas de conciliación, precedencia, equivalencia fiscal y cuarentena.
La comparten la evaluación (`eodhd_ab_eval`) y —en P0.2— el pipeline productivo, para que no puedan
divergir. Aquí NO hay red ni pandas: funciones puras sobre `companyfacts` ya descargados y sobre la
salida del conector EODHD. Reutiliza `reconcile_quality` del conector (no se reimplementa).

Principios (precisiones del usuario):
  - Reutiliza la lógica validada en E3.4; producción y evaluación usan estas mismas funciones.
  - Conserva estados EXPLÍCITOS por campo: verificado | parcial | desactualizado | inconsistente |
    faltante. No se asume que EODHD completa automáticamente los campos.
  - NO fabrica datos: FCF TTM y acciones diluidas sólo provienen de fuentes compatibles. El conector
    EODHD ya impone OCF−CAPEX del mismo período para FCF y NUNCA emite acciones diluidas; aquí,
    además, se descarta defensivamente cualquier `diluted_shares` de procedencia EODHD.
  - Preserva período y definición de cada métrica (anual vs TTM); no cambia el significado de
    métricas existentes. El enriquecimiento se entrega en un bloque aparte, nunca sobrescribe los
    campos oficiales de EDGAR.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Optional

from app.core.normalize import _best_annual, _best_instant
from app.core.connectors.eodhd import reconcile_quality
from app.core.connectors.registry import ProvenancedField

# Umbral de equivalencia fiscal: > un trimestre nuevo. <= se considera jitter de calendario del
# MISMO ejercicio económico y NO cuenta como más fresco (evita actualidad ficticia). Idéntico al de
# la evaluación A/B validada en E3.4.
MIN_FISCAL_GAP_DAYS = 75

# EDGAR nunca es sustituido por EODHD en estos campos: las acciones diluidas ponderadas sólo provienen
# de la fuente oficial (regla 5 de E3.4). Defensa en profundidad: aunque el conector no las emite.
_EODHD_FORBIDDEN = {"diluted_shares", "diluted_shares_annual"}

# Contraparte EDGAR de cada campo EODHD (para leer su estado de vigencia). Los `*_annual` y los
# interinos del mismo concepto comparten contraparte; capex/total_debt/fcf/eps mantienen su concepto.
_COUNTERPART = {
    "revenue": "revenue", "revenue_annual": "revenue",
    "net_income": "net_income", "net_income_annual": "net_income",
    "ocf": "ocf", "ocf_annual": "ocf",
    "cash": "cash", "cash_annual": "cash",
    "capex": "capex", "capex_annual": "capex",
    "total_debt": "net_debt", "total_debt_annual": "net_debt",
    "fcf": "fcf_ttm", "fcf_annual": "fcf_annual",
    "eps_ttm": "eps_ttm", "eps_annual": "eps_annual",
}


def edgar_annual_series(facts: dict, tax: str, M: dict, ccy: Optional[str]) -> Dict[str, dict]:
    """Serie anual (y de caja, instantánea) de EDGAR por campo: {campo: {'YYYY-MM-DD': valor}}.
    Es el insumo de `reconcile_quality` para cotejar EODHD contra la fuente oficial en el MISMO
    período y moneda. Movida desde `eodhd_ab_eval` para ser la ÚNICA definición compartida."""
    out: Dict[str, dict] = {}
    for field, concepts, inst in (("revenue", M["rev"], False), ("net_income", M["ni"], False),
                                  ("ocf", M["ocf"], False), ("cash", M["cash"], True)):
        pts = (_best_instant if inst else _best_annual)(facts, tax, concepts, ccy)
        out[field] = {d.isoformat(): v for d, v in pts}
    return out


def edgar_annual_history(facts: dict, tax: str, M: dict, ccy: Optional[str], n: int = 6) -> list:
    """Historia ANUAL oficial (EDGAR companyfacts) para gráficos de evolución: últimos `n` ejercicios
    con revenue, net_income, operating_income, ocf, capex, fcf (=ocf−|capex|), cash, gross_debt,
    net_debt y márgenes (op/net). Fuente oficial; no inventa (campo ausente → None). Un solo origen,
    reutilizado por producción y por el on-demand."""
    from app.core.normalize import _best_annual, _best_instant

    def ser(key, instant=False):
        concepts = M.get(key) or []
        pts = (_best_instant if instant else _best_annual)(facts, tax, concepts, ccy)
        return {d.isoformat(): v for d, v in pts}

    rev, ni, opi = ser("rev"), ser("ni"), ser("op_income")
    ocf, capex = ser("ocf"), ser("capex")
    cash = ser("cash", instant=True)
    dlt, dcur, dcomb = ser("debt_lt", True), ser("debt_cur", True), ser("debt_combined", True)
    years = sorted(set(rev) | set(ni) | set(ocf) | set(cash))[-n:]
    out = []
    for y in years:
        r, netinc, op = rev.get(y), ni.get(y), opi.get(y)
        o, cx = ocf.get(y), capex.get(y)
        fcf = (o - abs(cx)) if (o is not None and cx is not None) else None
        gd = dcomb.get(y)
        if gd is None and (dlt.get(y) is not None or dcur.get(y) is not None):
            gd = (dlt.get(y) or 0) + (dcur.get(y) or 0)
        c = cash.get(y)
        nd = (gd - c) if (gd is not None and c is not None) else None
        rec = {"period_end": y, "revenue": r, "net_income": netinc, "operating_income": op,
               "ocf": o, "capex": cx, "fcf": fcf, "cash": c, "gross_debt": gd, "net_debt": nd,
               "op_margin": (op / r) if (op is not None and r) else None,
               "net_margin": (netinc / r) if (netinc is not None and r) else None}
        out.append(rec)
    return out


def is_materially_fresher(eodhd_period: Optional[date], edgar_data_end: Optional[date],
                          min_days: int = MIN_FISCAL_GAP_DAYS) -> bool:
    """¿El período EODHD es MATERIALMENTE posterior al último período económico de EDGAR (un nuevo
    trimestre), y no sólo una fecha calendario ligeramente distinta del mismo ejercicio? Sin período
    EODHD → no aporta. Sin período EDGAR → cualquier período EODHD con fecha es un aporte. Idéntico a
    la regla de la evaluación A/B (`(pe - data_end).days <= 75` descarta como jitter)."""
    if eodhd_period is None:
        return False
    if edgar_data_end is None:
        return True
    return (eodhd_period - edgar_data_end).days > min_days


_PERIOD_TOL = 0.10   # ±10% para clasificar un flujo contra su ejercicio anual

# Elegibilidad para valoración por tipo de período. Un flujo de UN trimestre o un YTD acumulado NO
# es base de valoración (se necesita anual o TTM); un saldo de balance (caja/deuda) sí es insumo
# (último stock). EPS de EODHD es base ambigua → nunca apto (regla 2). 'indeterminado' → no apto.
_VALUATION_ELIGIBLE_PERIODS = {"anual", "ttm", "balance_instantaneo"}


def classify_period_type(quarterly: dict, yearly: dict, tol: float = _PERIOD_TOL) -> str:
    """Clasifica un FLUJO como 'trimestre_individual' | 'ytd_acumulado' | 'indeterminado', cotejando la
    serie trimestral contra el ejercicio anual (Σ4T ≈ anual → trimestres; T-cierre ≈ anual → YTD). No
    basta `period_end`: el significado depende del emisor/endpoint (p. ej. el OCF de ASML es YTD)."""
    if not yearly:
        return "indeterminado"
    yk = sorted(yearly)[-1]
    A = yearly.get(yk)
    if not A:
        return "indeterminado"
    y = int(str(yk)[:4])
    qin = {d: v for d, v in sorted((quarterly or {}).items()) if f"{y-1}-" < str(d) <= yk}
    q_close = (quarterly or {}).get(yk)
    sum4 = sum(list(qin.values())[-4:]) if qin else None
    if q_close is not None and abs(q_close / A - 1) <= tol:
        return "ytd_acumulado"
    if sum4 is not None and abs(sum4 / A - 1) <= tol:
        return "trimestre_individual"
    return "indeterminado"


def valuation_eligible(period_type: Optional[str], eps_base_ambigua: bool = False) -> bool:
    """¿El dato es apto para valoración fundamental? Sólo anual/TTM/saldo de balance; un trimestre
    suelto, un YTD o un período indeterminado, no. EPS de base ambigua, nunca."""
    if eps_base_ambigua:
        return False
    return period_type in _VALUATION_ELIGIBLE_PERIODS


def _parse(s) -> Optional[date]:
    try:
        p = str(s)[:10].split("-")
        return date(int(p[0]), int(p[1]), int(p[2]))
    except (ValueError, IndexError, TypeError):
        return None


def enrich_fundamentals(
    eodhd_fields: Dict[str, ProvenancedField],
    edgar_series: dict,
    edgar_data_end: Optional[date],
    same_currency: bool,
    edgar_states: Dict[str, str],
    min_days: int = MIN_FISCAL_GAP_DAYS,
) -> Dict[str, dict]:
    """Decide, campo por campo, qué aporta EODHD sobre el ancla EDGAR, con estados explícitos.

    Parámetros:
      - `eodhd_fields`: salida CRUDA del conector (`{campo: ProvenancedField}`). La conciliación se
        aplica aquí una sola vez (`reconcile_quality`).
      - `edgar_series`: `edgar_annual_series(...)` para cotejar mismo período/moneda.
      - `edgar_data_end`: último período económico de EDGAR (equivalencia fiscal).
      - `same_currency`: si la moneda EODHD coincide con la de reporte EDGAR.
      - `edgar_states`: estado de vigencia de EDGAR por contraparte de campo
        (vigente | presente_no_vigente | faltante | bloqueado | no_aplica).

    Devuelve `{campo: {...}}` con:
      - value, period, currency, filing, method, source (procedencia).
      - state ∈ {verificado, parcial, desactualizado, inconsistente, faltante}.
      - usable: True SÓLO si EODHD aporta un dato que llena un hueco o agrega actualidad material y
        no es inconsistente — nunca cuando EDGAR ya está vigente (precedencia del dato oficial).

    Reglas:
      - `inconsistente` → cuarentena: se conserva valor y estado para auditoría, pero usable=False.
      - EDGAR vigente en la contraparte → usable=False (se preserva el oficial verificado).
      - Aporta (usable=True) sólo si quality∈{verificado,parcial} Y período materialmente posterior Y
        EDGAR no vigente.
      - No fabrica: `diluted_shares` de EODHD se descarta; `fcf`/`fcf_ttm` sólo si el conector los
        entregó (ya exige OCF−CAPEX compatibles); un valor None → faltante.
    """
    reconciled = reconcile_quality(eodhd_fields, edgar_series, same_currency)
    out: Dict[str, dict] = {}
    for name, pf in reconciled.items():
        if name in _EODHD_FORBIDDEN:
            continue  # acciones diluidas ponderadas: sólo EDGAR/oficial, nunca EODHD
        counterpart = _COUNTERPART.get(name, name)
        edgar_state = edgar_states.get(counterpart, "faltante")
        period = _parse(pf.period)

        if pf.value is None:
            state, usable = "faltante", False
        elif pf.quality == "inconsistente":
            state, usable = "inconsistente", False          # cuarentena: registrado, no usado
        elif edgar_state == "vigente":
            state, usable = pf.quality, False                # precedencia: preservar oficial vigente
        elif pf.quality in ("verificado", "parcial") and is_materially_fresher(period, edgar_data_end, min_days):
            state, usable = pf.quality, True                 # llena hueco / agrega actualidad material
        else:
            # Presente pero no materialmente más fresco (mismo período) o calidad no positiva.
            state = "desactualizado" if edgar_state in ("presente_no_vigente", "faltante") else pf.quality
            usable = False

        out[name] = {
            "value": pf.value, "state": state, "usable": usable,
            "period": pf.period, "currency": pf.currency, "filing": pf.as_of,
            "method": pf.method, "source": pf.provenance,
            "edgar_state": edgar_state,
        }
    return out
