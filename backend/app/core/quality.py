"""Calidad de datos: validación de múltiplos, cobertura por factor y suficiencia.

Objetivo: que el ranking no se contamine con cifras imposibles (como un P/E forward
de 4x por una anualización mal hecha, o un crecimiento de EPS de +900% por un dato
basura). Los valores implausibles se ANULAN con un motivo explícito; nunca se
corrigen inventando otro número.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Mapping, Optional, Tuple

import numpy as np

from .types import Fundamentals

# Rangos plausibles por métrica (fuera de rango => se anula con motivo).
BOUNDS: Dict[str, Tuple[float, float]] = {
    "pe_ttm": (0.0, 1000.0),          # P/E negativo no es "barato": se anula (ver abajo)
    "pe_forward": (0.0, 1000.0),
    "ev_ebitda": (0.0, 500.0),
    "fcf_yield": (-1.0, 1.0),         # -100%..100%
    "roic": (-5.0, 5.0),              # -500%..500%
    "roe": (-5.0, 5.0),
    "rev_growth_yoy": (-1.0, 10.0),   # -100%..+1000%
    "eps_growth_yoy": (-1.0, 10.0),
    "net_margin": (-10.0, 1.0),       # margen > 100% es imposible
    "debt_to_equity": (-50.0, 100.0),
    "market_cap": (0.0, 1e14),
}

# Factores del scanner y las métricas que los alimentan (para medir cobertura).
FACTOR_METRICS: Dict[str, List[str]] = {
    "value": ["pe_forward", "ev_ebitda", "fcf_yield"],
    "quality": ["roic", "roe", "net_margin", "debt_to_equity"],
    "growth": ["rev_growth_yoy", "eps_growth_yoy"],
}


def validate_fundamentals(f: Optional[Fundamentals]) -> Tuple[Optional[Fundamentals], List[dict]]:
    """Devuelve (fundamentales saneados, lista de incidencias).

    Cada incidencia: {field, value, reason}. El campo problemático queda en None.
    """
    if f is None:
        return None, []
    issues: List[dict] = []
    updates: Dict[str, Optional[float]] = {}
    for field, (lo, hi) in BOUNDS.items():
        v = getattr(f, field, None)
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            updates[field] = None
            issues.append({"field": field, "value": v, "reason": "no numérico"})
            continue
        if not np.isfinite(x):
            updates[field] = None
            issues.append({"field": field, "value": v, "reason": "no finito"})
        elif x < lo or x > hi:
            updates[field] = None
            issues.append({"field": field, "value": x,
                           "reason": f"fuera de rango plausible [{lo}, {hi}]"})
    if updates:
        f = replace(f, **updates)
    return f, issues


def coverage_report(fundamentals_by_ticker: Mapping[str, Optional[Fundamentals]]) -> Dict[str, float]:
    """Fracción del universo con AL MENOS una métrica presente por factor (0-1)."""
    n = len(fundamentals_by_ticker) or 1
    out: Dict[str, float] = {}
    for factor, metrics in FACTOR_METRICS.items():
        present = 0
        for f in fundamentals_by_ticker.values():
            if f is None:
                continue
            if any(getattr(f, m, None) is not None for m in metrics):
                present += 1
        out[factor] = present / n
    return out


def usable_factors(coverage: Mapping[str, float], min_coverage: float) -> List[str]:
    """Factores cuya cobertura alcanza el mínimo; el resto se excluye del compuesto."""
    return [f for f, c in coverage.items() if c >= min_coverage]


def count_present_metrics(f: Optional[Fundamentals]) -> int:
    if f is None:
        return 0
    allm = [m for ms in FACTOR_METRICS.values() for m in ms]
    return sum(1 for m in allm if getattr(f, m, None) is not None)


def is_sufficient(f: Optional[Fundamentals], min_metrics: int = 3) -> bool:
    """¿Hay datos fundamentales suficientes para rankear con confianza?"""
    return count_present_metrics(f) >= min_metrics


# =================================================================================
# MOTOR DE CALIDAD DEL FDE (E1) — extraído de providers/edgar.py SIN cambiar la lógica.
# Añade al saneo por rangos de arriba: (1) guard de plausibilidad de magnitudes/saltos,
# (2) routing por tipo de instrumento (señal universal por SIC), (3) clasificación por campo.
# =================================================================================


def assess_plausibility(ni_l: Optional[float], rev_l: Optional[float],
                        eg_raw: Optional[float], rg_raw: Optional[float]) -> Tuple[str, Optional[str]]:
    """Detecta magnitudes imposibles / saltos implausibles → (data_quality, quality_reason).

    Mismos umbrales que el guard original del parser (NI>ingresos → bloqueado; |ΔEPS|>3 → bloqueado;
    margen neto>0.6 → sospechoso; 1.5<|ΔEPS|≤3 → sospechoso). La ÚNICA diferencia respecto del
    original es REDACTAR la razón del salto de EPS de forma NEUTRAL: describe la anomalía y la deja
    bloqueada pendiente de contraste con documentos oficiales, sin atribuirla al emisor ni al 10-K
    (E1, cond. 5: no imputar la anomalía de MU al emisor sin evidencia documental).
    """
    data_quality, quality_reason = "ok", None
    if ni_l is not None and rev_l and ni_l > rev_l:
        data_quality = "bloqueado"
        quality_reason = f"utilidad neta ({ni_l:.4g}) > ingresos ({rev_l:.4g}) — magnitud imposible; verificar documento original"
    elif eg_raw is not None and abs(eg_raw) > 3.0:
        data_quality = "bloqueado"
        quality_reason = (f"salto de EPS interanual {eg_raw*100:.0f}% implausible"
                          + (f" (ingresos {rg_raw*100:.0f}% con multiplicador distinto)" if rg_raw is not None else "")
                          + "; anomalía no resuelta — bloqueado hasta contrastar con documentos financieros oficiales")
    elif (ni_l is not None and rev_l) and (ni_l / rev_l) > 0.6:
        data_quality = "sospechoso"
        nm = ni_l / rev_l
        quality_reason = f"margen neto {nm*100:.0f}% inusualmente alto; posible dato extraordinario o erróneo (verificar sector)"
    elif eg_raw is not None and abs(eg_raw) > 1.5:
        data_quality = "sospechoso"
        quality_reason = f"salto de EPS interanual {eg_raw*100:.0f}% — posible ciclicidad extrema o error; verificar"
    return data_quality, quality_reason


# Códigos SIC de la SEC que identifican VEHÍCULOS de inversión, no empresas operativas. Señal
# UNIVERSAL (metadato de la SEC), no una lista de tickers. Los trusts de materias primas (oro,
# plata, platino…) y fondos no generan ingresos ni utilidades en sentido corporativo: aplicarles
# EPS/ROE/márgenes produce cifras sin significado económico (E1, cond. 2).
#   6221 Commodity Contracts Brokers & Dealers (p. ej. trusts de oro/plata/metales)
#   6726 Investment Offices NEC (fondos cerrados / vehículos)
#   6770 Blank Checks (SPAC y vehículos sin operación)
#   6189 Asset-Backed Securities
# Se EXCLUYEN a propósito bancos (6020-6029), aseguradoras (631x/641x) y procesadores de pagos
# (7389, p. ej. V/MA): ESOS sí son empresas operativas con EPS/ingresos con significado económico.
FUND_TRUST_SIC = {6221, 6726, 6770, 6189}

_NON_OP_DESC_KW = ("commodity", "trust", "blank check", "investment offices", "asset-backed", "unit investment")
_OP_DESC_KW = ("bank", "insurance", "savings", "credit", "services-")


def is_non_operating(sic: Optional[int], sic_desc: Optional[str] = None) -> bool:
    """True si el instrumento es un vehículo de inversión (ETF/trust/fondo), no una empresa operativa.

    Señal primaria: código SIC en `FUND_TRUST_SIC`. Señal secundaria (sólo si hay descripción y el
    código no resuelve): palabras clave de vehículo en la descripción, excluyendo explícitamente
    bancos/aseguradoras/servicios que sí son operativos. Universal: no depende del ticker.
    """
    try:
        sic_i = int(sic) if sic is not None and str(sic).strip() != "" else None
    except (ValueError, TypeError):
        sic_i = None
    if sic_i is not None and sic_i in FUND_TRUST_SIC:
        return True
    if sic_desc:
        d = sic_desc.lower()
        if any(k in d for k in _OP_DESC_KW):
            return False
        if any(k in d for k in _NON_OP_DESC_KW):
            return True
    return False


# Tipos de instrumento de la capa de IDENTIDAD (services/identity.py) que NO son empresas
# operativas (no se les calculan EPS/ROE/márgenes) y los que SÍ lo son.
_NON_OP_ITYPES = {"etf", "commodity_etf", "commodity_trust", "fund", "trust",
                  "closed_end_fund", "unit_investment_trust", "etn"}
_OP_ITYPES = {"stock", "common", "common_stock", "equity", "adr", "gdr"}


def classify_instrument(instrument_type: Optional[str], sic: Optional[int] = None,
                        sic_desc: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """Clasifica el instrumento → (instrument_class, nota).

    instrument_class ∈ {empresa_operativa, etf_o_trust, indeterminado}.

    `instrument_type` de la capa de IDENTIDAD es la señal PRIMARIA; el SIC de la SEC es
    COMPLEMENTO, no clasificación universal (E1, verificación pre-merge). Reglas:
      1. Identidad dice vehículo (ETF/trust/fondo) → etf_o_trust (aunque el SIC calle).
      2. Identidad dice operativa:
         - si el SIC contradice (indica vehículo) → indeterminado (NO habilitar métricas).
         - si no → empresa_operativa.
      3. Identidad ausente/unknown → apoyarse en SIC SIN asumir operativa:
         - SIC indica vehículo → etf_o_trust.
         - SIC conocido y operativo → empresa_operativa.
         - sin SIC → indeterminado (no se asume operativa sin ninguna señal).
    """
    it = (instrument_type or "").strip().lower()
    sic_nonop = is_non_operating(sic, sic_desc)
    sic_known = (sic is not None and str(sic).strip() != "") or bool(sic_desc)

    if it in _NON_OP_ITYPES:
        return "etf_o_trust", f"identidad={instrument_type} (vehículo); métricas corporativas no aplican"
    if it in _OP_ITYPES:
        if sic_nonop:
            return "indeterminado", (f"contradicción: identidad={instrument_type} (operativa) vs "
                                     f"SIC={sic} ({sic_desc}) sugiere vehículo; no se habilitan "
                                     "métricas corporativas hasta resolver")
        return "empresa_operativa", None
    # Identidad ausente o 'unknown': el SIC es complemento, no se asume operativa.
    if sic_nonop:
        return "etf_o_trust", f"sin instrument_type; SIC={sic} ({sic_desc}) indica vehículo"
    if sic_known:
        return "empresa_operativa", f"sin instrument_type; SIC={sic} ({sic_desc}) indica empresa operativa"
    return "indeterminado", "sin instrument_type ni SIC: tipo de instrumento no determinado"


def classify_field(value, *, independent: bool = False, derived: bool = False,
                   blocked: bool = False, not_applicable: bool = False) -> str:
    """Estado de UN campo. Separa DISPONIBILIDAD de EXACTITUD (E1 cond. 3): 'verificado' indica que
    el dato existe y es DIRECTO/consistente de forma independiente, no que se auditó su cifra exacta.
      - no_aplica   : el campo no tiene significado para este instrumento (ETF/trust).
      - bloqueado   : marcado por el guard de plausibilidad; no usar.
      - faltante    : sin dato.
      - derivado    : reconstruido/calculado (p. ej. NI = EPS×acciones), no reportado directo.
      - parcial     : disponible pero sin verificación independiente.
      - verificado  : reportado directo y con consistencia independiente.
    """
    if not_applicable:
        return "no_aplica"
    if blocked:
        return "bloqueado"
    if value in (None, ""):
        return "faltante"
    if derived:
        return "derivado"
    if independent:
        return "verificado"
    return "parcial"
