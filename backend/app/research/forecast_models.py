"""P1.8 — Modelos de proyección fundamental (PUROS, testeables) para el backtest PIT.

Operan sobre una serie anual REPORTADA ordenada y un índice base `ti`: solo usan datos de años
≤ ti (sin look-ahead). Proyectan ingresos, margen EBIT y FCFF a horizontes 1/2/3.

Modelos (reglas A-PRIORI, sin ajustar parámetros a los períodos de evaluación):
  A  GIIC sin consenso : g1 = clamp(CAGR 4a de ingresos, [gT, 0.25]); fade lineal a gT en 8 años.
  C  reinversión×ROIC  : g = reinversión_t / capital_invertido_t (Damodaran: g = RR·ROIC);
                         aplicable solo si capital invertido y NOPAT > 0.
  D  baseline histórico: g = mediana del crecimiento interanual de ingresos (últimos 4 años).
El MARGEN EBIT se mantiene en el promedio móvil de 3 años en TODOS los modelos (se compara la regla
de CRECIMIENTO de forma limpia). FCFF = NOPAT − reinversión; reinversión_{t+k} = ΔIngresos/ventas-
a-capital (mediana histórica). B (consenso) NO se incluye: no hay vintages históricos (ver informe)."""
from __future__ import annotations

from statistics import median
from typing import Dict, List, Optional

GIIC_CAP = 0.25


def taxrate(series: List[dict], ti: int) -> float:
    rs = [r for r in series[: ti + 1] if r.get("pretax") and r.get("tax") is not None and r["pretax"] > 0]
    if not rs:
        return 0.15
    t = median([r["tax"] / r["pretax"] for r in rs[-4:]])
    return min(0.35, max(0.10, t))


def rev_cagr(series: List[dict], ti: int, n: int = 4) -> Optional[float]:
    lo = ti - n
    if lo < 0 or series[lo]["revenue"] <= 0 or series[ti]["revenue"] <= 0:
        return None
    return (series[ti]["revenue"] / series[lo]["revenue"]) ** (1.0 / n) - 1.0


def median_yoy(series: List[dict], ti: int, n: int = 4) -> Optional[float]:
    gs = []
    for k in range(max(1, ti - n + 1), ti + 1):
        p = series[k - 1]["revenue"]
        if p and p > 0:
            gs.append(series[k]["revenue"] / p - 1.0)
    return median(gs) if gs else None


def trailing_margin(series: List[dict], ti: int, n: int = 3) -> Optional[float]:
    ms = [r["ebit_margin"] for r in series[max(0, ti - n + 1): ti + 1] if r.get("ebit_margin") is not None]
    return sum(ms) / len(ms) if ms else None


def _reinvestment(r: dict) -> Optional[float]:
    if r.get("capex") is None:
        return None
    # capex crudo EODHD suele venir negativo => abs; reinversión neta = capex − D&A + ΔWC
    cap = abs(r["capex"]); dna = r.get("dna") or 0.0; wc = r.get("wc_change") or 0.0
    return cap - dna + wc


def sales_to_capital(series: List[dict], ti: int, n: int = 5) -> Optional[float]:
    ratios = []
    for k in range(max(1, ti - n + 1), ti + 1):
        drev = series[k]["revenue"] - series[k - 1]["revenue"]
        ri = _reinvestment(series[k])
        if ri and ri > 0 and drev > 0:
            ratios.append(drev / ri)
    return median(ratios) if ratios else None


def invested_capital(series: List[dict], ti: int) -> Optional[float]:
    ic = 0.0
    seen = False
    for r in series[: ti + 1]:
        ri = _reinvestment(r)
        if ri is not None:
            ic += ri
            seen = True
    return ic if (seen and ic > 0) else None


def _fade(g1: float, gT: float, k: int, years: int = 8) -> float:
    return g1 + (gT - g1) * min(k - 1, years) / years


def growth_rule(model: str, series: List[dict], ti: int, gT: float) -> dict:
    """Devuelve {g1, applicable, note}. El crecimiento por horizonte se obtiene con _fade(g1,...)."""
    if model == "A":
        c = rev_cagr(series, ti, 4)
        if c is None:
            return {"applicable": False, "note": "sin CAGR (historia insuficiente)"}
        return {"g1": min(GIIC_CAP, max(gT, c)), "applicable": True}
    if model == "D":
        m = median_yoy(series, ti, 4)
        if m is None:
            return {"applicable": False, "note": "sin crecimiento histórico"}
        return {"g1": m, "applicable": True}
    if model == "C":
        ri = _reinvestment(series[ti]); ic = invested_capital(series, ti)
        ebit = series[ti].get("ebit"); tr = taxrate(series, ti)
        if ri is None or ic is None or ic <= 0 or ebit is None or ebit <= 0:
            return {"applicable": False, "note": "reinversión/capital invertido/NOPAT no válidos"}
        g = ri / ic                      # g = reinversión / capital invertido = RR·ROIC
        return {"g1": max(-0.2, min(GIIC_CAP, g)), "applicable": True}
    raise ValueError(model)


def project(model: str, series: List[dict], ti: int, gT: float,
            horizons=(1, 2, 3)) -> Dict[int, Optional[dict]]:
    gr = growth_rule(model, series, ti, gT)
    out: Dict[int, Optional[dict]] = {}
    if not gr.get("applicable"):
        for h in horizons:
            out[h] = None
        out["note"] = gr.get("note")
        return out
    g1 = gr["g1"]
    m = trailing_margin(series, ti)
    tr = taxrate(series, ti)
    s2c = sales_to_capital(series, ti) or 1.5
    rev = series[ti]["revenue"]; rev_prev = rev
    cum = {}
    revk = rev
    for k in range(1, max(horizons) + 1):
        g = _fade(g1, gT, k)
        revk_new = revk * (1 + g)
        ebit = revk_new * m if m is not None else None
        nopat = ebit * (1 - tr) if ebit is not None else None
        reinvest = (revk_new - revk) / s2c
        fcff = (nopat - reinvest) if nopat is not None else None
        cum[k] = {"revenue": revk_new, "ebit_margin": m, "ebit": ebit, "reinvest": reinvest,
                  "nopat": nopat, "fcff": fcff, "g": g}
        revk = revk_new
    for h in horizons:
        out[h] = cum.get(h)
    out["g1"] = g1
    out["s2c"] = s2c
    return out


# ---- métricas ----
def rel_error(forecast: Optional[float], actual: Optional[float]) -> Optional[float]:
    if forecast is None or actual is None or actual == 0:
        return None
    return forecast / actual - 1.0
