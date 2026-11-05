"""Pruebas del SampleProvider y de su integración con el núcleo.

Confirman que (a) los datos salen marcados como ejemplo, (b) son reproducibles,
(c) alimentan correctamente indicadores, analítica y scanner end-to-end sin red.
"""
import pandas as pd

from app.core import indicators as ind
from app.core import portfolio as pf
from app.core import scanner as sc
from app.core.types import AssetClass, Instrument, Position
from app.providers import get_provider
from app.providers.sample import SampleProvider


def test_factory_returns_sample():
    p = get_provider("sample")
    assert isinstance(p, SampleProvider) and p.is_sample is True


def test_quotes_are_marked_sample():
    p = SampleProvider()
    q = p.get_quotes(["NVDA", "VOO"])
    assert q["NVDA"].is_sample is True
    assert q["NVDA"].price > 0


def test_history_reproducible_and_ends_near_seed():
    p = SampleProvider()
    s1 = p.get_price_history("NVDA")
    s2 = p.get_price_history("NVDA")
    assert s1.equals(s2)                       # determinista
    assert abs(s1.iloc[-1] - 183.0) < 1e-6     # termina en el precio semilla


def test_fundamentals_marked_and_optional():
    p = SampleProvider()
    f = p.get_fundamentals(["NVDA", "GLD"])    # GLD no tiene fundamentales => omitido
    assert f["NVDA"].is_sample is True
    assert "GLD" not in f


def test_etf_holdings_contain_nvda():
    p = SampleProvider()
    smh = {h.ticker: h.weight for h in p.get_etf_holdings("SMH")}
    assert "NVDA" in smh and smh["NVDA"] > 0


def test_end_to_end_lookthrough_with_sample():
    p = SampleProvider()
    positions = [
        Position(p_inst(p, "NVDA"), 10, 100),
        Position(p_inst(p, "QQQ"), 10, 400),
        Position(p_inst(p, "SMH"), 10, 200),
    ]
    tickers = [x.instrument.ticker for x in positions]
    prices = {t: q.price for t, q in p.get_quotes(tickers).items()}
    holdings = {t: p.get_etf_holdings(t) for t in tickers}
    lt = pf.look_through_exposure(positions, prices, holdings)
    rep = pf.concentration_report(lt, max_weight_per_asset=0.25)
    tickers_eff = [r["ticker"] for r in lt["effective_exposure"]]
    assert "NVDA" in tickers_eff
    assert rep["hhi"] > 0


def test_end_to_end_scanner_with_sample():
    p = SampleProvider()
    universe = p.list_universe()
    inputs = []
    funds = p.get_fundamentals([i.ticker for i in universe])
    for inst in universe:
        hist = p.get_price_history(inst.ticker)
        inputs.append(sc.ScanInput(
            ticker=inst.ticker,
            fundamentals=funds.get(inst.ticker),
            technical=ind.snapshot(hist),
            is_sample=True,
        ))
    ranking = sc.rank(inputs, top=5)
    assert 1 <= len(ranking) <= 5
    assert all(r["is_sample"] for r in ranking)
    assert ranking[0]["composite"] >= ranking[-1]["composite"]


def p_inst(provider, ticker) -> Instrument:
    for i in provider.list_universe():
        if i.ticker == ticker:
            return i
    # ETFs no están en list_universe (solo equities); construye uno mínimo
    return Instrument(ticker, ticker, AssetClass.ETF, "US", "US", "ETF", "USD")
