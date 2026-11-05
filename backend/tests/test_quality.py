"""Pruebas de calidad de datos: validación de múltiplos, cobertura, suficiencia."""
from app.core import quality as q
from app.core.types import Fundamentals


def test_negative_pe_is_nullified():
    f = Fundamentals(ticker="X", pe_forward=-12.0)
    clean, issues = q.validate_fundamentals(f)
    assert clean.pe_forward is None
    assert any(i["field"] == "pe_forward" for i in issues)


def test_impossible_margin_nullified():
    f = Fundamentals(ticker="X", net_margin=1.5)  # >100% imposible
    clean, issues = q.validate_fundamentals(f)
    assert clean.net_margin is None


def test_absurd_eps_growth_nullified():
    f = Fundamentals(ticker="X", eps_growth_yoy=50.0)  # +5000% implausible
    clean, _ = q.validate_fundamentals(f)
    assert clean.eps_growth_yoy is None


def test_plausible_values_kept():
    f = Fundamentals(ticker="X", pe_forward=22.0, net_margin=0.34, roe=0.30, rev_growth_yoy=0.2)
    clean, issues = q.validate_fundamentals(f)
    assert clean.pe_forward == 22.0 and issues == []


def test_coverage_report_fractions():
    funds = {
        "A": Fundamentals(ticker="A", pe_forward=10, roic=0.2, rev_growth_yoy=0.1),
        "B": Fundamentals(ticker="B", pe_forward=20),           # solo value
        "C": None,                                              # sin datos
    }
    cov = q.coverage_report(funds)
    assert abs(cov["value"] - 2 / 3) < 1e-9     # A y B
    assert abs(cov["quality"] - 1 / 3) < 1e-9   # solo A
    assert abs(cov["growth"] - 1 / 3) < 1e-9


def test_usable_factors_threshold():
    cov = {"value": 0.8, "quality": 0.3, "growth": 0.6}
    assert set(q.usable_factors(cov, 0.5)) == {"value", "growth"}


def test_sufficiency():
    rich = Fundamentals(ticker="R", pe_forward=10, roic=0.2, rev_growth_yoy=0.1)
    poor = Fundamentals(ticker="P", pe_forward=10)
    assert q.is_sufficient(rich, min_metrics=3)
    assert not q.is_sufficient(poor, min_metrics=3)
    assert not q.is_sufficient(None)
