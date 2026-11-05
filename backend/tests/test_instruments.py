"""Pruebas de identificación de instrumentos (Fase A)."""
from app.jobs.instruments import (build_universe_instrument_rows, resolve_extra_tickers,
                                  resolve_instrument)


def test_universe_rows_identify_nvda_and_qqq():
    rows = {r["ticker"]: r for r in build_universe_instrument_rows()}
    assert rows["NVDA"]["name"] == "NVIDIA" and rows["NVDA"]["asset_class"] == "equity"
    assert rows["QQQ"]["asset_class"] == "etf"
    assert all(r["status"] == "resolved" and r["source"] == "universe"
               for r in rows.values())


def test_resolve_instrument_from_yahoo_meta():
    meta = {"name": "Micron Technology", "asset_class": "equity",
            "exchange": "NasdaqGS", "currency": "USD"}
    r = resolve_instrument("MU", meta)
    assert r["name"] == "Micron Technology" and r["asset_class"] == "equity"
    assert r["status"] == "resolved" and r["source"] == "yahoo"


def test_resolve_instrument_unknown_is_pending():
    r = resolve_instrument("ZZZZ", {}, edgar_name=None)
    assert r["asset_class"] == "unknown" and r["status"] == "pending"


def test_resolve_instrument_edgar_name_fallback():
    r = resolve_instrument("XYZ", {}, edgar_name="Example Corp")
    assert r["name"] == "Example Corp" and r["status"] == "pending"  # sin tipo => pending


def test_resolve_extra_tickers_tolerates_failure():
    class FakeYahoo:
        def get_instrument_meta(self, t):
            if t == "BOOM":
                raise RuntimeError("timeout")
            return {"name": "Apple Inc", "asset_class": "equity", "currency": "USD"}
    rows = {r["ticker"]: r for r in resolve_extra_tickers(["AAPL", "BOOM"], FakeYahoo(), {})}
    assert rows["AAPL"]["status"] == "resolved"
    assert rows["BOOM"]["status"] == "pending"   # falló la resolución => pending
