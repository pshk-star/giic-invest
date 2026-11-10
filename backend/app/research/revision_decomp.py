"""P1.7.2 — DECOMPOSICIÓN DE REVISIONES de expectativas (pura, testeable).

Compara dos snapshots del MISMO métrico (p.ej. estimate:revenue) capturados en fechas distintas
y distingue un cambio REAL de artefactos que NO deben leerse como revisión económica:
  - período fiscal distinto (el 'año en curso' rodó a otro período),
  - cambio de moneda,
  - split (métricos por acción: ratio ≈ entero limpio o su inverso),
  - error de escala (ratio ≈ potencia de 10),
  - cambio de cobertura de analistas (nº de analistas se movió materialmente).

Un cambio real POSITIVO NO es señal de compra: solo actualiza la expectativa que alimenta el FCFF.
"""
from __future__ import annotations

from typing import Optional

PER_SHARE_KINDS = {"estimate:eps", "analyst_target_rating", "forward_multiple"}


def _near(ratio: float, target: float, tol: float = 0.03) -> bool:
    return abs(ratio - target) <= tol * target


def classify_revision(prev: dict, curr: dict, kind: str) -> dict:
    """prev/curr = payloads pit_snapshots del mismo kind/ticker, fechas distintas. Devuelve la
    clasificación y si el cambio es utilizable como revisión económica real."""
    pv, cv = (prev or {}).get("value"), (curr or {}).get("value")
    flags = []
    # período fiscal
    if (prev or {}).get("fiscal_period_end") != (curr or {}).get("fiscal_period_end"):
        return {"classification": "periodo_fiscal_distinto", "usable_as_real_revision": False,
                "flags": ["fiscal_period_rolled"],
                "note": "comparación entre períodos fiscales distintos: no es una revisión del mismo objeto"}
    # moneda
    if (prev or {}).get("currency") != (curr or {}).get("currency"):
        return {"classification": "moneda_distinta", "usable_as_real_revision": False,
                "flags": ["currency_changed"], "note": "cambio de moneda: reconciliar antes de interpretar"}
    if pv in (None, 0) or cv is None:
        return {"classification": "incompleto", "usable_as_real_revision": False, "flags": ["missing_value"]}
    ratio = cv / pv
    pct = ratio - 1.0
    # split (solo métricos por acción)
    if kind in PER_SHARE_KINDS:
        for k in (2, 3, 4, 5, 10):
            if _near(ratio, k) or _near(ratio, 1.0 / k):
                return {"classification": "split_sospechado", "usable_as_real_revision": False,
                        "flags": [f"split_x{k}"], "ratio": round(ratio, 4),
                        "note": "ratio ≈ entero limpio: posible split; ajustar antes de interpretar"}
    # error de escala (potencia de 10)
    for p in (1000.0, 1e6, 1e-3, 1e-6):
        if _near(ratio, p, tol=0.05):
            return {"classification": "error_escala", "usable_as_real_revision": False,
                    "flags": ["scale_error"], "ratio": round(ratio, 4),
                    "note": "ratio ≈ potencia de 10: desajuste de unidades/escala, no revisión"}
    # cobertura de analistas
    na_p, na_c = (prev or {}).get("n_analysts"), (curr or {}).get("n_analysts")
    if na_p and na_c and na_p > 0 and abs(na_c - na_p) / na_p > 0.20:
        flags.append("coverage_changed")
    out = {"classification": "revision_real", "usable_as_real_revision": True,
           "pct_change": round(pct, 4), "ratio": round(ratio, 4), "flags": flags,
           "note": "revisión económica real; una revisión positiva NO es señal de compra por sí sola"}
    if "coverage_changed" in flags:
        out["note"] = ("cambio de cobertura de analistas (" + f"{na_p:.0f}→{na_c:.0f}" +
                       "): el cambio de media puede deberse a la muestra, no a nueva información")
    return out
