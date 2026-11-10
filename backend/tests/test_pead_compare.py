"""P1.7 Fase 2 — pruebas PURAS (sin red) del Modelo C (sorpresa/PEAD) y controles estadísticos."""
from __future__ import annotations

from app.research.pead_compare import (sue, surprise_pct, surprise_streak, days_since_report,
                                       drift_since_report, surprise_features, holm)
from app.research.model_spec import MODEL_C, SURPRISE_FEATURES, MODELS, RESEARCH_MODELS


def _hist():
    # 8 trimestres con reportDate creciente; última sorpresa positiva grande
    base = []
    for i, (rd, diff, sp) in enumerate([
        ("2024-02-01", 0.10, 5.0), ("2024-05-01", 0.12, 6.0), ("2024-08-01", -0.05, -2.0),
        ("2024-11-01", 0.08, 4.0), ("2025-02-01", 0.15, 7.0), ("2025-05-01", 0.20, 9.0),
        ("2025-08-01", 0.25, 11.0), ("2025-11-01", 0.30, 13.0)]):
        base.append({"reportDate": rd, "epsActual": 1 + diff, "epsEstimate": 1.0,
                     "epsDifference": diff, "surprisePercent": sp})
    return base


def test_reportdate_strictly_before_decision_no_lookahead():
    h = _hist()
    # decisión el 2025-11-01 (mismo día del report): convención conservadora excluye ese report
    av = [x for x in h if x["reportDate"] < "2025-11-01"]
    assert len(av) == 7
    # la racha a esa fecha NO incluye el report del propio día
    assert surprise_streak(h, "2025-11-01") is not None


def test_sue_standardizes_last_surprise():
    h = _hist()
    s = sue(h, "2026-01-01")
    assert s is not None and s > 0  # última sorpresa (0.30) muy por encima de la media => SUE alto


def test_streak_positive_run_normalized():
    h = _hist()
    # desde 2024-11 en adelante todas positivas: racha positiva (normalizada a <=1)
    st = surprise_streak(h, "2026-01-01")
    assert 0 < st <= 1.0


def test_surprise_pct_scaled():
    assert abs(surprise_pct(_hist(), "2026-01-01") - 0.13) < 1e-9


def test_days_since_report_normalized_and_capped():
    assert days_since_report(_hist(), "2025-11-10") is not None
    # a >180 días se satura en 2.0 (180/90)
    assert days_since_report(_hist(), "2027-01-01") == 2.0


def test_drift_uses_only_past_prices():
    h = _hist()
    # último reportDate < 2025-11-10 es 2025-11-01; la sesión en/antes es 2025-10-31 (j=1):
    # mide del cierre 2025-10-31 (101) a i=3 (110) = 0.0891, SOLO precios pasados
    dts = ["2025-10-30", "2025-10-31", "2025-11-03", "2025-11-10"]
    closes = [100.0, 101.0, 105.0, 110.0]
    assert abs(drift_since_report(h, "2025-11-10", dts, closes, 3) - (110.0 / 101.0 - 1.0)) < 1e-9
    # sin ninguna sesión en/antes del report => None (no inventa ancla)
    assert drift_since_report(h, "2025-11-10", ["2025-11-05", "2025-11-10"], [100.0, 110.0], 1) is None


def test_surprise_features_order_and_completeness():
    h = _hist()
    dts = ["2025-08-01", "2025-09-01", "2025-10-01", "2025-11-10"]
    closes = [100.0, 102.0, 108.0, 120.0]
    f = surprise_features(h, "2025-11-10", dts, closes, 3)
    assert f is not None and len(f) == len(SURPRISE_FEATURES) == 5
    # devuelve None si falta cualquiera (historia insuficiente)
    assert surprise_features([], "2025-11-10", dts, closes, 3) is None


def test_holm_controls_multiple_comparisons():
    # p pequeñas pasan; una grande no. Holm es más estricto que sin corregir.
    out = holm({"t1": 0.001, "t2": 0.04, "t3": 0.20}, alpha=0.05)
    assert out["t1"]["reject_H0"] is True
    assert out["t3"]["reject_H0"] is False
    # t2 con Holm: umbral 0.05/2=0.025 < 0.04 => NO se rechaza (sin corregir sí se habría rechazado)
    assert out["t2"]["reject_H0"] is False


def test_surprise_pit_classification():
    from app.research.surprise_pit_probe import classify
    hist = {f"2024-{m:02d}-01": {"reportDate": f"2024-{m:02d}-05", "beforeAfterMarket": "AfterMarket",
            "epsEstimate": 1.0, "epsActual": 1.1, "epsDifference": 0.1, "surprisePercent": 10.0}
            for m in range(1, 13)}
    hist.update({f"2025-{m:02d}-01": {"reportDate": f"2025-{m:02d}-05", "beforeAfterMarket": "BeforeMarket",
                 "epsEstimate": 1.0, "epsActual": 1.2, "epsDifference": 0.2, "surprisePercent": 20.0}
                 for m in range(1, 7)})
    res = classify(hist)
    assert res["classification"] == "PIT_ESTRICTO"   # >=12 trimestres con reportDate+est+actual
    assert res["with_beforeAfterMarket"] == res["n_quarters"]
    # sin reportDate => exploratorio
    bad = {"2024-01-01": {"epsEstimate": 1.0, "epsActual": 1.1}}
    assert classify(bad)["classification"] == "EXPLORATORIO"


def test_model_c_frozen_spec_not_in_production_plan():
    assert MODEL_C["version"] == "c-1.0.0"
    assert MODEL_C["features"][-5:] == SURPRISE_FEATURES
    assert MODEL_C not in MODELS            # producción NO emite C
    assert MODEL_C in RESEARCH_MODELS       # solo investigación
    assert MODEL_C["status"].startswith("EXPERIMENTAL")
