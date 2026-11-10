"""P1.7.2 — pruebas de la decomposición de revisiones (cambio real vs artefactos)."""
from __future__ import annotations

from app.research.revision_decomp import classify_revision


def _p(value, fpe="2026-12-31", ccy="USD", n=30):
    return {"value": value, "fiscal_period_end": fpe, "currency": ccy, "n_analysts": n}


def test_real_revision():
    r = classify_revision(_p(1000), _p(1050), "estimate:revenue")
    assert r["classification"] == "revision_real" and r["usable_as_real_revision"] is True
    assert abs(r["pct_change"] - 0.05) < 1e-9
    assert "no es señal de compra" in r["note"].lower() or "no es señal" in r["note"].lower()


def test_fiscal_period_rolled():
    r = classify_revision(_p(1000, fpe="2026-12-31"), _p(1200, fpe="2027-12-31"), "estimate:revenue")
    assert r["classification"] == "periodo_fiscal_distinto" and r["usable_as_real_revision"] is False


def test_currency_changed():
    r = classify_revision(_p(1000, ccy="USD"), _p(1000, ccy="TWD"), "estimate:revenue")
    assert r["classification"] == "moneda_distinta" and r["usable_as_real_revision"] is False


def test_split_detected_on_per_share():
    r = classify_revision(_p(10.0), _p(5.0), "estimate:eps")   # ratio 0.5 = 1/2
    assert r["classification"] == "split_sospechado" and r["usable_as_real_revision"] is False


def test_scale_error_detected():
    r = classify_revision(_p(1000), _p(1_000_000), "estimate:revenue")  # x1000
    assert r["classification"] == "error_escala" and r["usable_as_real_revision"] is False


def test_coverage_change_flagged_but_usable():
    r = classify_revision(_p(1000, n=30), _p(1050, n=10), "estimate:revenue")
    assert r["classification"] == "revision_real"
    assert "coverage_changed" in r["flags"]


def test_missing_value():
    r = classify_revision(_p(None), _p(1000), "estimate:revenue")
    assert r["usable_as_real_revision"] is False
