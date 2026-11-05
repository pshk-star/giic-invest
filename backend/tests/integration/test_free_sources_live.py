"""Integración REAL con las fuentes gratuitas: Stooq, SEC EDGAR y Frankfurter.

Se omite salvo que exportes RUN_LIVE_FREE=1 (y EDGAR_USER_AGENT con tu correo).
Requiere red; por eso NO corre en el sandbox de construcción. Ejecuta:

    RUN_LIVE_FREE=1 EDGAR_USER_AGENT="GIIC tu@correo.com" \
    pytest tests/integration/test_free_sources_live.py -v

Valida estructura y coherencia (precio>0, fechas ordenadas, fundamentales presentes,
FX positivo), nunca valores de mercado concretos.
"""
import os
from datetime import date

import pytest

httpx = pytest.importorskip("httpx")
pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_FREE") != "1",
                                reason="RUN_LIVE_FREE!=1 (prueba en vivo desactivada)")


def test_stooq_prices_live():
    from app.providers.stooq import StooqProvider
    s = StooqProvider().get_price_history("AAPL", start=date(2024, 1, 1), end=date(2024, 3, 1))
    assert len(s) > 10 and (s > 0).all()
    assert list(s.index) == sorted(s.index)


def test_edgar_fundamentals_live():
    from app.providers.edgar import EDGARProvider
    ua = os.getenv("EDGAR_USER_AGENT", "")
    f = EDGARProvider(user_agent=ua).get_fundamentals(["AAPL"], prices={"AAPL": 200.0})
    assert "AAPL" in f
    af = f["AAPL"]
    assert af.net_margin is not None or af.rev_growth_yoy is not None
    assert af.pe_forward is None and af.ev_ebitda is None  # honestos: no disponibles


def test_frankfurter_fx_live():
    from app.providers.frankfurter import FrankfurterProvider
    rates = FrankfurterProvider().get_fx_rates("USD", ["MXN", "EUR"])
    assert rates.get("MXN", 0) > 0 and rates.get("EUR", 0) > 0


def test_composite_scan_live():
    """El 'free' compuesto produce un ranking válido con datos reales."""
    from app.providers import get_provider
    from app.services.scan_engine import run_scan
    from app.jobs.universe import get_universe
    from app.jobs.validation import validate_scan_result
    prov = get_provider("free", edgar_user_agent=os.getenv("EDGAR_USER_AGENT", ""))
    res = run_scan(prov, get_universe()[:15], cache=None, today=date.today(), top=10,
                   min_coverage=0.4, sector_relative=True)
    ok, reasons = validate_scan_result(res, date.today(), min_evaluated=5)
    assert ok, reasons
    assert len(res["ranking"]) > 0 and not res["using_sample_data"]
