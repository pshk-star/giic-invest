"""P1.8 — Clasificación TRANSPARENTE de confianza de GIIC (pura, testeable).

La confianza ALTA requiere EVIDENCIA (error histórico OOS medido y bajo + corroboración), no se
asigna por pasar controles. Cinco criterios, cada uno con veredicto explícito:
  1. Integridad/procedencia de datos (eligible/degraded/…).
  2. Error histórico fuera de muestra (MAE de ingresos, modelo A, h=1).
  3. Corroboración de consenso independiente (corroborado / por_encima_guidance / ninguno).
  4. Sensibilidad a WACC/crecimiento/terminal (dispersión de escenarios (opt−cons)/base).
  5. Concentración de valor en supuestos lejanos (peso del valor terminal).

Umbrales a-priori (documentados). El nivel final es el PEOR entre los criterios duros; 'alta' exige
que TODOS cumplan y que exista error OOS medido.
"""
from __future__ import annotations

from typing import Optional

MAE_ALTA, MAE_MEDIA = 0.10, 0.20        # error rel. de ingresos h=1 (mediana)
SPREAD_ALTA, SPREAD_MEDIA = 1.0, 2.0    # dispersión de escenarios
TW_ALTA, TW_MEDIA = 0.60, 0.75          # peso terminal


def _rank(x: str) -> int:
    return {"alta": 3, "media": 2, "baja": 1}.get(x, 1)


def score_confidence(data_eligibility: str, oos_mae_rev_h1: Optional[float],
                     consensus: str, scenario_spread: Optional[float],
                     terminal_weight: Optional[float]) -> dict:
    crit = {}

    # 1. datos
    crit["datos"] = "alta" if data_eligibility == "eligible" else ("media" if data_eligibility == "degraded" else "baja")

    # 2. error OOS (SIN evidencia => no puede ser alta)
    if oos_mae_rev_h1 is None:
        crit["error_oos"] = "baja"   # sin evidencia histórica medida => no se premia
        oos_note = "sin error OOS medido"
    elif oos_mae_rev_h1 <= MAE_ALTA:
        crit["error_oos"] = "alta"; oos_note = None
    elif oos_mae_rev_h1 <= MAE_MEDIA:
        crit["error_oos"] = "media"; oos_note = None
    else:
        crit["error_oos"] = "baja"; oos_note = None

    # 3. corroboración
    crit["corroboracion"] = {"corroborado": "alta", "por_encima_guidance": "media",
                             "ninguno": "baja"}.get(consensus, "baja")

    # 4. sensibilidad
    if scenario_spread is None:
        crit["sensibilidad"] = "media"
    elif scenario_spread <= SPREAD_ALTA:
        crit["sensibilidad"] = "alta"
    elif scenario_spread <= SPREAD_MEDIA:
        crit["sensibilidad"] = "media"
    else:
        crit["sensibilidad"] = "baja"

    # 5. concentración terminal
    if terminal_weight is None:
        crit["concentracion_terminal"] = "media"
    elif terminal_weight <= TW_ALTA:
        crit["concentracion_terminal"] = "alta"
    elif terminal_weight <= TW_MEDIA:
        crit["concentracion_terminal"] = "media"
    else:
        crit["concentracion_terminal"] = "baja"

    # nivel = peor criterio (alta exige que TODOS sean alta, lo que incluye error OOS medido y bajo)
    level = min(crit.values(), key=_rank)
    reasons = [f"{k}={v}" for k, v in crit.items()]
    out = {"nivel": level, "criterios": crit, "detalle": reasons}
    if oos_note:
        out["nota"] = oos_note
    return out
