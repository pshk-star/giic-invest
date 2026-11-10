"""P1.8 — pruebas de la rúbrica de confianza (alta requiere evidencia)."""
from __future__ import annotations

from app.research.confidence_rubric import score_confidence


def test_alta_requires_all_criteria_including_measured_oos():
    r = score_confidence("eligible", 0.08, "corroborado", 0.8, 0.55)
    assert r["nivel"] == "alta"


def test_no_oos_evidence_cannot_be_alta():
    # datos ok, corroborado, poca sensibilidad, pero SIN error OOS medido => no alta
    r = score_confidence("eligible", None, "corroborado", 0.8, 0.55)
    assert r["nivel"] == "baja"
    assert r["criterios"]["error_oos"] == "baja"


def test_worst_criterion_drives_level():
    # todo alta salvo concentración terminal muy alta => baja
    r = score_confidence("eligible", 0.08, "corroborado", 0.8, 0.90)
    assert r["criterios"]["concentracion_terminal"] == "baja" and r["nivel"] == "baja"


def test_above_guidance_caps_at_media():
    r = score_confidence("eligible", 0.09, "por_encima_guidance", 0.8, 0.55)
    assert r["criterios"]["corroboracion"] == "media" and r["nivel"] == "media"


def test_degraded_data_limits():
    r = score_confidence("degraded", 0.08, "corroborado", 0.8, 0.55)
    assert r["criterios"]["datos"] == "media" and r["nivel"] == "media"
