"""Pruebas de analítica de cartera, con foco en el look-through de ETF."""
import numpy as np
import pandas as pd

from app.core import portfolio as pf
from app.core.types import AssetClass, ETFHolding, Instrument, Position


def _inst(t, ac=AssetClass.EQUITY, sector="Tech", country="US", ccy="USD"):
    return Instrument(t, t, ac, "US", country, sector, ccy)


def test_position_pnl():
    p = Position(_inst("NVDA"), quantity=10, avg_cost=100.0)
    r = pf.position_pnl(p, price=120.0)
    assert r["market_value"] == 1200.0
    assert r["cost_basis"] == 1000.0
    assert r["pnl"] == 200.0
    assert abs(r["pnl_pct"] - 0.20) < 1e-9


def test_valuation_weights_sum_to_one():
    positions = [
        Position(_inst("NVDA"), 10, 100),
        Position(_inst("KO", sector="Staples"), 20, 50),
    ]
    val = pf.portfolio_valuation(positions, {"NVDA": 120, "KO": 60})
    w = sum(r["weight"] for r in val["positions"])
    assert abs(w - 1.0) < 1e-9
    assert val["total_market_value"] == 10 * 120 + 20 * 60


def test_missing_price_is_reported_not_invented():
    positions = [Position(_inst("NVDA"), 10, 100), Position(_inst("XYZ"), 5, 10)]
    val = pf.portfolio_valuation(positions, {"NVDA": 120})  # falta XYZ
    assert "XYZ" in val["missing_prices"]
    xyz = [r for r in val["positions"] if r["ticker"] == "XYZ"][0]
    assert xyz["market_value"] is None


def test_fx_conversion():
    # posición en MXN convertida a base USD
    p = Position(_inst("WALMEX", country="MX", ccy="MXN"), 100, 70.0)
    val = pf.portfolio_valuation([p], {"WALMEX": 70.0}, fx={"MXN": 1 / 18.5})
    mv = val["positions"][0]["market_value"]
    assert abs(mv - (100 * 70.0 / 18.5)) < 1e-6


def test_look_through_combines_direct_and_etf():
    """Caso central: NVDA directa + QQQ + SMH => exposición efectiva a NVDA mayor
    que el peso nominal de la posición directa."""
    positions = [
        Position(_inst("NVDA"), 10, 100),                       # 10*180 = 1800 directo
        Position(_inst("QQQ", AssetClass.ETF, "ETF"), 10, 400), # 10*480 = 4800 ETF
        Position(_inst("SMH", AssetClass.ETF, "ETF"), 10, 200), # 10*260 = 2600 ETF
    ]
    prices = {"NVDA": 180, "QQQ": 480, "SMH": 260}
    holdings = {
        "QQQ": [ETFHolding("NVDA", 0.085), ETFHolding("MSFT", 0.08)],
        "SMH": [ETFHolding("NVDA", 0.20), ETFHolding("TSM", 0.12)],
    }
    lt = pf.look_through_exposure(positions, prices, holdings)
    eff = {r["ticker"]: r["effective_value"] for r in lt["effective_exposure"]}
    expected_nvda = 1800 + 4800 * 0.085 + 2600 * 0.20
    assert abs(eff["NVDA"] - expected_nvda) < 1e-6
    # el peso efectivo de NVDA supera su peso directo nominal
    total = lt["total_market_value"]
    assert eff["NVDA"] / total > 1800 / total


def test_look_through_residual_when_partial_coverage():
    positions = [Position(_inst("QQQ", AssetClass.ETF, "ETF"), 10, 100)]
    holdings = {"QQQ": [ETFHolding("NVDA", 0.3)]}  # solo 30% cubierto
    lt = pf.look_through_exposure(positions, {"QQQ": 100}, holdings)
    eff = {r["ticker"]: r["effective_value"] for r in lt["effective_exposure"]}
    assert abs(eff["NVDA"] - 1000 * 0.3) < 1e-6
    assert abs(eff["QQQ:resto"] - 1000 * 0.7) < 1e-6
    assert lt["coverage_warnings"][0]["etf"] == "QQQ"


def test_herfindahl_and_effective_holdings():
    assert abs(pf.herfindahl([0.25, 0.25, 0.25, 0.25]) - 0.25) < 1e-9
    assert abs(pf.effective_number_of_holdings([0.25, 0.25, 0.25, 0.25]) - 4.0) < 1e-9
    assert pf.herfindahl([1.0]) == 1.0


def test_concentration_breach_flagged():
    lt = {"effective_exposure": [
        {"ticker": "NVDA", "effective_value": 40, "effective_weight": 0.40},
        {"ticker": "KO", "effective_value": 60, "effective_weight": 0.60},
    ], "total_market_value": 100}
    rep = pf.concentration_report(lt, max_weight_per_asset=0.25)
    breached = {b["ticker"] for b in rep["breaches"]}
    assert breached == {"NVDA", "KO"}


def test_distribution_by_sector():
    positions = [
        Position(_inst("NVDA", sector="Semis"), 10, 100),
        Position(_inst("KO", sector="Staples"), 10, 100),
    ]
    val = pf.portfolio_valuation(positions, {"NVDA": 100, "KO": 100})
    dist = pf.distribution(val, "sector")
    assert abs(dist["Semis"] - 0.5) < 1e-9 and abs(dist["Staples"] - 0.5) < 1e-9


def test_correlation_matrix_diagonal_is_one():
    idx = pd.bdate_range("2020-01-01", periods=100)
    rng = np.random.default_rng(3)
    hist = {
        "A": pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 100))), index=idx),
        "B": pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 100))), index=idx),
    }
    corr = pf.correlation_matrix(hist)
    assert abs(corr.loc["A", "A"] - 1.0) < 1e-9
