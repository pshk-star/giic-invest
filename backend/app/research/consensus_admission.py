"""P1.7.3 — GATE DE ADMISIÓN de consenso prospectivo (puro, testeable).

Causa raíz hallada (ver informe P1.7.3): EODHD `Earnings.Trend` está indexado por FECHA y guarda el
histórico completo; `period` ('0y','+1y','0q','+1q') es relativo a la fecha de CADA registro, no a
hoy. En P1.7.2 se leyó un registro antiguo (p.ej. NVDA 2018 '0y' = 9,5B). La corrección es
SELECCIONAR por fecha el registro del año fiscal vigente (≥ hoy).

Este módulo (1) selecciona los registros anuales vigente (CY) y siguiente (NY) por fecha, y (2)
aplica controles de admisión. Los datos que NO pasan quedan EXCLUIDOS (no se corrigen con supuestos):
  - moneda = moneda de reporte,
  - escala: nivel del registro que solapa el año reportado ≈ reportado (±10%); CY vs reportado en banda,
  - consistencia nivel↔crecimiento: growth implícito entre anuales ≈ growth declarado (±8 pp),
  - coherencia EPS/acciones/NI: margen EBIT implícito del EPS en banda [0,6–1,4]×m0; net margin plausible,
  - cobertura de analistas ≥ mínimo,
  - frescura: UpdatedAt reciente,
  - ceros/obsoletos/extremos: EPS≤0 o crecimiento absurdo (>200%) excluyen; crecimiento alto pero
    consistente (p.ej. NVDA) se ADMITE marcado 'extremo' con confianza degradada.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

MIN_ANALYSTS = 10
SCALE_BAND_CY = (0.5, 3.0)         # ingreso CY vs último reportado (1 año adelante)
ANCHOR_TOL = 0.10                  # registro que solapa el año reportado vs reportado
LEVELGROWTH_TOL = 0.08             # |growth implícito − growth declarado|
MARGIN_BAND = (0.6, 1.4)           # margen EBIT implícito vs m0
NET_MARGIN_MAX = 0.75
GROWTH_ABSURD = 2.0                # >200% anual => dato roto (no 'agresivo')
GROWTH_EXTREME = 0.80              # alto pero posible => admitir + marcar + degradar
FRESH_DAYS = 120


def _d(s: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def select_fiscal_records(trend_list: List[dict], today: date):
    """Devuelve (cy, prev, ny): registros ANUALES (period termina en 'y') por fecha.
    cy = primer anual con fecha ≥ hoy; prev = último anual con fecha < hoy; ny = siguiente a cy."""
    annual = [r for r in trend_list if str(r.get("period", "")).endswith("y") and _d(r.get("date"))]
    annual.sort(key=lambda r: _d(r["date"]))
    fut = [r for r in annual if _d(r["date"]) >= today]
    past = [r for r in annual if _d(r["date"]) < today]
    cy = fut[0] if fut else None
    ny = fut[1] if len(fut) > 1 else None
    prev = past[-1] if past else None
    return cy, prev, ny


def _reconcile_margin(eps, shares, revenue, interest, tax_rate):
    if not (eps and revenue and shares) or tax_rate >= 1.0:
        return None
    ni = eps * shares
    ebit = ni / (1 - tax_rate) + (interest or 0.0)
    return {"ni": ni, "ebit": ebit, "margin": ebit / revenue, "net_margin": ni / revenue}


@dataclass
class Reported:
    ccy: str
    revenue: float
    shares: float
    ni: float
    ebit_margin0: float
    interest: float
    tax_rate: float
    fiscal_year_end: str   # fecha YYYY-MM-DD del último ejercicio reportado


def admit_consensus(ticker: str, trend_list: List[dict], rep: Reported, today: date,
                    updated_at: Optional[str]) -> dict:
    """Aplica el gate. Devuelve admisión CY/NY + checks + confianza + razones de exclusión."""
    checks: Dict[str, dict] = {}
    reasons: List[str] = []
    cy, prev, ny = select_fiscal_records(trend_list, today)

    # (0) existe período fiscal vigente
    if cy is None:
        return {"admitted": False, "confidence": "na", "reasons": ["sin registro anual vigente (date ≥ hoy)"]}

    rev_cy = cy.get("revEstAvg"); g_cy = cy.get("revGrowth"); eps_cy = cy.get("epsEstAvg")
    na_cy = cy.get("revAnalysts") or cy.get("epsAnalysts")

    # (1) moneda
    ok_ccy = True  # la moneda se valida a nivel objeto (General.CurrencyCode==rep.ccy) aguas arriba
    checks["currency"] = {"ok": ok_ccy, "ccy": rep.ccy}

    # (2) ancla de escala: el registro anual que solapa el año reportado ≈ reportado
    anchor = None
    fy = _d(rep.fiscal_year_end)
    if fy:
        cands = [r for r in trend_list if str(r.get("period", "")).endswith("y") and _d(r.get("date"))
                 and abs((_d(r["date"]) - fy).days) <= 45]   # mismo ejercicio (tolerante a fin de mes fiscal)
        anchor = min(cands, key=lambda r: abs((_d(r["date"]) - fy).days)) if cands else None
    if anchor and anchor.get("revEstAvg"):
        ratio = anchor["revEstAvg"] / rep.revenue
        ok = abs(ratio - 1.0) <= ANCHOR_TOL
        checks["scale_anchor"] = {"ok": ok, "ratio_vs_reported": round(ratio, 4)}
        if not ok:
            reasons.append(f"registro del año reportado desalineado vs reportado (ratio {ratio:.3f})")
    else:
        checks["scale_anchor"] = {"ok": False, "note": "sin registro que solape el año reportado"}
        reasons.append("sin ancla de escala (no hay registro del año reportado)")

    # (3) escala CY vs reportado (1 año adelante)
    scale_cy = (rev_cy / rep.revenue) if rev_cy else None
    ok_scale = scale_cy is not None and SCALE_BAND_CY[0] <= scale_cy <= SCALE_BAND_CY[1]
    checks["scale_cy"] = {"ok": ok_scale, "ratio": round(scale_cy, 4) if scale_cy else None}
    if not ok_scale:
        reasons.append(f"nivel CY fuera de banda vs reportado ({scale_cy})")

    # (4) consistencia nivel↔crecimiento (growth implícito entre anuales ≈ declarado)
    if prev and prev.get("revEstAvg") and rev_cy and g_cy is not None:
        implied = rev_cy / prev["revEstAvg"] - 1.0
        ok = abs(implied - g_cy) <= LEVELGROWTH_TOL
        checks["level_growth"] = {"ok": ok, "implied": round(implied, 4), "declared": g_cy}
        if not ok:
            reasons.append(f"nivel y crecimiento inconsistentes (implícito {implied:.3f} vs declarado {g_cy})")
    else:
        checks["level_growth"] = {"ok": None, "note": "sin anual previo para verificar"}

    # (5) coherencia EPS/acciones/NI → margen EBIT implícito
    rec = _reconcile_margin(eps_cy, rep.shares, rev_cy, rep.interest, rep.tax_rate)
    if rec:
        lo, hi = MARGIN_BAND[0] * rep.ebit_margin0, MARGIN_BAND[1] * rep.ebit_margin0
        ok = lo <= rec["margin"] <= hi and 0 < rec["net_margin"] <= NET_MARGIN_MAX
        checks["eps_margin"] = {"ok": ok, "implied_ebit_margin": round(rec["margin"], 4),
                                "net_margin": round(rec["net_margin"], 4)}
        if not ok:
            reasons.append(f"margen EBIT implícito del EPS fuera de banda ({rec['margin']:.3f})")
    else:
        checks["eps_margin"] = {"ok": False, "note": "EPS no utilizable (0/ausente)"}
        reasons.append("EPS de consenso no utilizable")

    # (6) cobertura
    ok_cov = bool(na_cy and na_cy >= MIN_ANALYSTS)
    checks["coverage"] = {"ok": ok_cov, "n_analysts": na_cy}
    if not ok_cov:
        reasons.append(f"cobertura insuficiente ({na_cy} analistas)")

    # (7) frescura
    upd = _d((updated_at or "")[:10])
    fresh = upd is not None and (today - upd).days <= FRESH_DAYS
    checks["freshness"] = {"ok": fresh, "updated_at": updated_at}
    if not fresh:
        reasons.append("consenso obsoleto (UpdatedAt no reciente)")

    # (8) ceros/absurdos/extremos
    extreme = False
    if g_cy is None or eps_cy in (None, 0, 0.0):
        reasons.append("valor cero/ausente en CY")
    elif abs(g_cy) > GROWTH_ABSURD:
        reasons.append(f"crecimiento absurdo ({g_cy})")
    elif g_cy > GROWTH_EXTREME:
        extreme = True
    checks["extreme"] = {"flag": extreme, "g_cy": g_cy}

    hard = ["scale_anchor", "scale_cy", "eps_margin", "coverage", "freshness"]
    admitted = not reasons and all(checks.get(k, {}).get("ok") for k in hard)
    confidence = "na"
    if admitted:
        confidence = "baja" if extreme else "media"
    return {
        "admitted": admitted, "confidence": confidence,
        "cy": {"fiscal_end": cy.get("date"), "rev_growth": g_cy, "rev_level": rev_cy,
               "eps": eps_cy, "n_analysts": na_cy},
        "ny": ({"fiscal_end": ny.get("date"), "rev_growth": ny.get("revGrowth"),
                "rev_level": ny.get("revEstAvg"), "eps": ny.get("epsEstAvg"),
                "n_analysts": ny.get("revAnalysts")} if ny else None),
        "checks": checks, "reasons": reasons, "extreme": extreme,
    }
