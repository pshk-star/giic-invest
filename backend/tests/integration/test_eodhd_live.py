"""Pruebas de integración REALES contra EODHD.

Se omiten automáticamente si no hay EODHD_API_KEY en el entorno (y si httpx no está
instalado). Ejecutar con:

    EODHD_API_KEY=tu_clave pytest tests/integration/test_eodhd_live.py -v

Validan que el conector habla de verdad con la API y que los datos llegan con la
forma esperada. No se asume ningún valor concreto de mercado; solo estructura y
coherencia (precio > 0, fechas ordenadas, moneda presente).
"""
import os
from datetime import date

import pytest

httpx = pytest.importorskip("httpx")
API_KEY = os.getenv("EODHD_API_KEY")
pytestmark = pytest.mark.skipif(not API_KEY, reason="EODHD_API_KEY no configurada")


@pytest.fixture(scope="module")
def provider():
    from app.providers.eodhd import EODHDProvider
    return EODHDProvider(api_key=API_KEY, default_exchange="US")


def test_quote_real(provider):
    q = provider.get_quotes(["AAPL"])
    assert "AAPL" in q and q["AAPL"].price > 0 and q["AAPL"].is_sample is False


def test_history_real_sorted(provider):
    s = provider.get_price_history("AAPL", start=date(2024, 1, 1), end=date(2024, 3, 1))
    assert len(s) > 10
    assert list(s.index) == sorted(s.index)       # fechas ascendentes
    assert (s > 0).all()


def test_fundamentals_real(provider):
    f = provider.get_fundamentals(["AAPL"])
    assert "AAPL" in f and f["AAPL"].market_cap and f["AAPL"].market_cap > 0


def test_etf_holdings_real(provider):
    holdings = provider.get_etf_holdings("QQQ")
    assert len(holdings) > 0
    assert all(0 <= h.weight <= 1 for h in holdings)


def test_fx_real(provider):
    rates = provider.get_fx_rates("USD", ["EUR"])
    assert "EUR" in rates and rates["EUR"] > 0


def test_health_real(provider):
    h = provider.health()
    assert h["ok"] is True and h["is_sample"] is False
