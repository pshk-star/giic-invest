"""P1.7.2 — Motor de EXPECTATIVAS FUNDAMENTALES (experimental).

Combina: financieros reportados (base) + consenso de ingresos/EPS + supuestos GIIC + ajustes
sectoriales documentados, y produce SENDAS año a año (crecimiento + margen EBIT) para tres
escenarios SEPARADOS:
  A = CONSENSO de analistas (cuando existe).
  B = proyección FUNDAMENTAL PROPIA de GIIC (= senda mecánica P1.6; nuestro benchmark).
  C = COMBINADO con reglas DOCUMENTADAS (ramp decreciente consenso→GIIC; sin pesos arbitrarios).

Regla clave: NO se convierte EPS estimado directamente en EBIT. El EPS de consenso se RECONCILIA
(acciones → NI → pretax vía tasa → EBIT sumando interés neto) y el margen implícito solo INFORMA
la senda, acotado a una banda de plausibilidad; si cae fuera, se marca incoherencia y se DEGRADA
la confianza (o se abstiene). Si faltan datos o los períodos fiscales/moneda no coinciden con los
flujos, se degrada o se abstiene.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .fcff_forward import Assump, Base, p16_path


@dataclass
class Consensus:
    currency: Optional[str] = None
    rev_cy: Optional[float] = None       # ingresos estimados año en curso (CY)
    rev_ny: Optional[float] = None       # año siguiente (NY)
    g_cy: Optional[float] = None         # crecimiento estimado CY (si lo da el proveedor)
    g_ny: Optional[float] = None
    eps_cy: Optional[float] = None
    eps_ny: Optional[float] = None
    n_analysts: Optional[float] = None
    fiscal_cy_end: Optional[str] = None
    fiscal_ny_end: Optional[str] = None


def reconcile_eps_to_ebit(eps: Optional[float], shares: float, revenue: Optional[float],
                          interest: float, tax_rate: float) -> Optional[dict]:
    """Reconciliación EPS→EBIT (NO conversión directa). NI=EPS·acciones; pretax=NI/(1−tasa);
    EBIT≈pretax + interés neto (se readiciona el gasto financiero). Margen = EBIT/ingresos.
    Marcado `derived`; es una COMPROBACIÓN de coherencia, no un dato que mande sobre el margen."""
    if eps is None or revenue in (None, 0) or not shares:
        return None
    ni = eps * shares
    if tax_rate >= 1.0:
        return None
    pretax = ni / (1 - tax_rate)
    ebit = pretax + (interest or 0.0)     # interés>0 = gasto: se readiciona para llegar a EBIT
    return {"ni": ni, "pretax": pretax, "ebit": ebit, "margin": ebit / revenue,
            "quality": "derived",
            "note": "margen EBIT implícito del EPS de consenso; reconciliado vía NI→pretax→EBIT, no conversión directa"}


def _coherent_margin(implied: Optional[float], m0: float, band: Tuple[float, float] = (0.6, 1.4)):
    """Acota el margen implícito a [band·m0]; devuelve (margen_usado, coherente?)."""
    lo, hi = band[0] * m0, band[1] * m0
    if implied is None:
        return m0, None
    if lo <= implied <= hi:
        return implied, True
    return m0, False   # incoherente: se usa m0 reportado y se degradará la confianza


def _fade(start: float, end: float, i: int, i0: int, years: int) -> float:
    """Fade lineal desde el año i0 (valor start) hasta `years` (valor end)."""
    if i <= i0:
        return start
    return start + (end - start) * (i - i0) / (years - i0)


# Banda de crecimiento anual plausible para estas megacaps. Fuera de ella, el dato de consenso se
# considera no fiable (p.ej. nivel de ingresos de consenso en escala errónea => tasa derivada absurda).
GROWTH_CAP = 0.80
GROWTH_FLOOR = -0.50


def _plausible_growth(g: Optional[float]) -> bool:
    return g is not None and GROWTH_FLOOR <= g <= GROWTH_CAP


def consensus_path(base: Base, a: Assump, c: Consensus, gT: float) -> dict:
    """Escenario A. Usa la TASA de crecimiento declarada por el consenso (NO los niveles absolutos
    de ingresos, poco fiables/escala errónea en el proveedor); años 1-2 de consenso, 3..N fade a
    terminal. El margen se reconcilia desde el EPS contra la revenue DERIVADA (reportado×tasa), no
    contra el nivel de consenso. Controles de moneda, plausibilidad y coherencia degradan o abstienen."""
    years = a.years
    notes: List[str] = []
    data_quality: List[str] = []
    conf = "media"
    # ---- control de moneda (primero: si no coincide con los flujos, abstención) ----
    if c.currency and c.currency != base.ccy:
        return {"available": False, "reason": f"moneda de consenso {c.currency} ≠ moneda de flujos {base.ccy}; abstención",
                "confidence": "na", "data_quality": data_quality}
    # ---- data-quality de NIVELES (solo para MARCAR; no se usan para el crecimiento) ----
    if c.rev_cy and not (0.3 * base.revenue <= c.rev_cy <= 3.0 * base.revenue):
        data_quality.append(f"nivel rev_cy de consenso implausible vs reportado (ratio {c.rev_cy/base.revenue:.3f}); "
                            "se ignora el NIVEL y se usa la TASA declarada")
    # ---- crecimiento: tasa declarada; fallback a nivel solo si no hay tasa ----
    g1 = c.g_cy if c.g_cy is not None else ((c.rev_cy / base.revenue - 1.0) if c.rev_cy else None)
    g2 = c.g_ny if c.g_ny is not None else ((c.rev_ny / c.rev_cy - 1.0) if (c.rev_ny and c.rev_cy) else None)
    if not _plausible_growth(g1):
        return {"available": False, "reason": f"crecimiento CY de consenso no plausible ({g1}); no utilizable",
                "confidence": "na", "data_quality": data_quality}
    if not _plausible_growth(g2):
        g2 = gT + (g1 - gT) * 0.6   # sin NY fiable: decaimiento suave del CY
        notes.append("NY ausente/implausible: g2 por decaimiento de g1")
        conf = "baja"
    g = [g1, g2] + [_fade(g2, gT, i, 2, years) for i in range(3, years + 1)]
    # ---- margen: reconciliación EPS→EBIT contra revenue DERIVADA (reportado×tasa), acotado ----
    rev_y1 = base.revenue * (1 + g1)
    rev_y2 = rev_y1 * (1 + g2)
    eps_cy = c.eps_cy if (c.eps_cy and c.eps_cy > 0) else None   # eps<=0/ausente => sin reconciliación
    eps_ny = c.eps_ny if (c.eps_ny and c.eps_ny > 0) else None
    rec_cy = reconcile_eps_to_ebit(eps_cy, base.shares, rev_y1, base.interest, base.tax_rate)
    rec_ny = reconcile_eps_to_ebit(eps_ny, base.shares, rev_y2, base.interest, base.tax_rate)
    m1, ok1 = _coherent_margin(rec_cy["margin"] if rec_cy else None, base.ebit_margin0)
    m2, ok2 = _coherent_margin(rec_ny["margin"] if rec_ny else None, base.ebit_margin0)
    if ok1 is False or ok2 is False:
        notes.append("margen EBIT implícito del consenso INCOHERENTE vs reportado: se usa m0 y se degrada confianza")
        conf = "baja"
    if rec_cy is None:
        notes.append("sin EPS de consenso utilizable: margen = m0 reportado"); conf = "baja" if conf == "media" else conf
    m = [m1, m2] + [_fade(m2, a.margin_terminal, i, 2, years) for i in range(3, years + 1)]
    return {"available": True, "g": g, "m": m, "confidence": conf, "notes": notes,
            "data_quality": data_quality, "reconcile": {"cy": rec_cy, "ny": rec_ny},
            "provenance": {"g1": "tasa consenso CY", "g2": "tasa consenso NY" if c.g_ny is not None else "derivado",
                           "revenue_for_margin": "reportado×tasa (no nivel de consenso)",
                           "margin": "reconciliado EPS→EBIT (acotado)" if rec_cy else "m0 reportado",
                           "n_analysts": c.n_analysts}}


def giic_path(base: Base, a: Assump, gT: float) -> dict:
    """Escenario B = proyección fundamental propia de GIIC = senda mecánica P1.6 (benchmark)."""
    g, m = p16_path(a.g1, gT, base.ebit_margin0, a.margin_terminal, a.years)
    return {"available": True, "g": g, "m": m, "confidence": "media",
            "notes": ["senda GIIC = supuestos fundamentales P1.6 (benchmark)"],
            "provenance": {"g": "GIIC g1 + fade mecánica", "margin": "GIIC m0→mT"}}


# Pesos del escenario combinado: ramp DECRECIENTE del consenso. Fundamento (no arbitrario):
# las estimaciones de analistas tienen señal ~1-2 años; más allá se revierte a fundamentales GIIC.
COMBINED_WEIGHTS = [max(0.0, 0.70 - 0.175 * (i - 1)) for i in range(1, 11)]  # 0.70,0.525,0.35,0.175,0,...


def combined_path(path_a: dict, path_b: dict, years: int = 10) -> dict:
    """Escenario C. g_i^C = w_i·g_i^A + (1−w_i)·g_i^B (igual para margen). Reglas documentadas."""
    if not path_a.get("available"):
        return {"available": False, "reason": "consenso no disponible; C no se calcula", "confidence": "na"}
    w = COMBINED_WEIGHTS[:years]
    g = [w[i] * path_a["g"][i] + (1 - w[i]) * path_b["g"][i] for i in range(years)]
    m = [w[i] * path_a["m"][i] + (1 - w[i]) * path_b["m"][i] for i in range(years)]
    # confianza C = la menor entre A y B (conservador)
    rank = {"alta": 3, "media": 2, "baja": 1, "na": 0}
    conf = min(path_a.get("confidence", "baja"), path_b.get("confidence", "baja"), key=lambda z: rank.get(z, 0))
    return {"available": True, "g": g, "m": m, "confidence": conf,
            "weights": w, "notes": ["combinado: ramp consenso→GIIC (0.70→0 en 5 años); no se promedia a ciegas"]}


def consensus_from_eodhd(obj: dict) -> Consensus:
    """Arma Consensus desde el objeto EODHD /fundamentals vivo (consenso para valorar HOY, permitido
    por #7). Usa Earnings.Trend períodos '0y' (CY) y '+1y' (NY), con Highlights como respaldo de EPS."""
    obj = obj or {}
    gen = obj.get("General", {}) or {}
    trend = (obj.get("Earnings", {}) or {}).get("Trend", {}) or {}
    hi = obj.get("Highlights", {}) or {}
    by_period = {}
    for k, d in trend.items():
        p = (d or {}).get("period")
        if p in ("0y", "+1y"):
            by_period[p] = d
    c = Consensus(currency=gen.get("CurrencyCode"))

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    cy, ny = by_period.get("0y"), by_period.get("+1y")
    if cy:
        c.rev_cy = num(cy.get("revenueEstimateAvg")); c.g_cy = num(cy.get("revenueEstimateGrowth"))
        c.eps_cy = num(cy.get("earningsEstimateAvg")); c.n_analysts = num(cy.get("revenueEstimateNumberOfAnalysts"))
        c.fiscal_cy_end = cy.get("date")
    if ny:
        c.rev_ny = num(ny.get("revenueEstimateAvg")); c.g_ny = num(ny.get("revenueEstimateGrowth"))
        c.eps_ny = num(ny.get("earningsEstimateAvg")); c.fiscal_ny_end = ny.get("date")
    if c.eps_cy is None:
        c.eps_cy = num(hi.get("EPSEstimateCurrentYear"))
    if c.eps_ny is None:
        c.eps_ny = num(hi.get("EPSEstimateNextYear"))
    return c


def build_consensus_from_snapshots(rows: List[dict], base_ccy: str) -> Consensus:
    """Arma un Consensus desde filas pit_snapshots capturadas (kind estimate:revenue / forward_multiple).
    Toma los DOS períodos fiscales futuros más cercanos como CY/NY. PIT: usa solo lo capturado."""
    rev = sorted([r for r in rows if r.get("kind") == "estimate:revenue"
                  and (r.get("payload") or {}).get("fiscal_period_end")],
                 key=lambda r: r["payload"]["fiscal_period_end"])
    fm = next((r for r in rows if r.get("kind") == "forward_multiple"), None)
    c = Consensus()
    if rev:
        c.currency = (rev[0]["payload"] or {}).get("currency")
        c.rev_cy = rev[0]["payload"].get("value"); c.g_cy = rev[0]["payload"].get("growth")
        c.fiscal_cy_end = rev[0]["payload"].get("fiscal_period_end")
        c.n_analysts = rev[0]["payload"].get("n_analysts")
        if len(rev) > 1:
            c.rev_ny = rev[1]["payload"].get("value"); c.g_ny = rev[1]["payload"].get("growth")
            c.fiscal_ny_end = rev[1]["payload"].get("fiscal_period_end")
    if fm:
        c.eps_cy = (fm["payload"] or {}).get("eps_cy"); c.eps_ny = (fm["payload"] or {}).get("eps_ny")
    return c
