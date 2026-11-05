"""Pruebas de datos internacionales: FX, obsolescencia y tickers por bolsa."""
from datetime import date

from app.core import fx, symbols


# ---- FX ----
def test_convert_same_currency():
    r = fx.convert(100, "USD", "USD", {})
    assert r.ok and r.amount_base == 100 and r.rate == 1.0


def test_convert_with_rate():
    r = fx.convert(1000, "MXN", "USD", {"MXN": 0.054})
    assert r.ok and abs(r.amount_base - 54.0) < 1e-9


def test_convert_missing_rate_is_flagged_not_assumed():
    r = fx.convert(1000, "MXN", "USD", {})
    assert not r.ok and r.amount_base is None and "sin tasa" in r.reason


def test_build_rate_map_sets_base_one():
    m = fx.build_rate_map("USD", {"MXN": 0.054, "EUR": 1.08})
    assert m["USD"] == 1.0 and m["MXN"] == 0.054


# ---- obsolescencia ----
def test_fresh_quote_not_stale():
    assert not fx.is_stale(date(2026, 11, 4), date(2026, 11, 5), max_business_days=4)


def test_old_quote_is_stale():
    assert fx.is_stale(date(2026, 10, 1), date(2026, 11, 5), max_business_days=4)


def test_none_as_of_is_stale():
    assert fx.is_stale(None, date(2026, 11, 5))


def test_future_as_of_not_stale():
    assert not fx.is_stale(date(2026, 11, 6), date(2026, 11, 5))


def test_business_days_old_skips_weekend():
    # viernes a lunes = 1 día hábil
    assert fx.business_days_old(date(2026, 11, 6), date(2026, 11, 9)) == 1


# ---- símbolos ----
def test_parse_symbol_with_and_without_suffix():
    assert symbols.parse_symbol("NVDA.US") == ("NVDA", "US")
    assert symbols.parse_symbol("NVDA") == ("NVDA", "US")
    assert symbols.parse_symbol("2330.TW") == ("2330", "TW")


def test_parse_symbol_right_split_for_dotted_ticker():
    assert symbols.parse_symbol("BRK.B.US") == ("BRK.B", "US")


def test_currency_and_country_by_exchange():
    assert symbols.currency_for("WALMEX.MX") == "MXN"
    assert symbols.country_for("2330.TW") == "TW"
    assert symbols.currency_for("NVDA.US") == "USD"


def test_same_instrument_canonical():
    assert symbols.same_instrument("NVDA", "NVDA.US")
    assert not symbols.same_instrument("TSM.US", "2330.TW")
