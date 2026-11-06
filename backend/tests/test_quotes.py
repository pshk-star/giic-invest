"""Pruebas del parser de cotizaciones (sin red): cambio del día, rango, estado de mercado."""
from app.providers.yahoo import parse_quote_snapshot

REG_START, REG_END = 1_699_990_000, 1_700_020_000
NOW_OPEN = 1_700_000_000       # dentro de la sesión regular
NOW_CLOSED = 1_700_040_000     # después del post-market (REG_END + 20000 > fin de post)


def _payload():
    return {"chart": {"result": [{
        "meta": {
            "regularMarketPrice": 102.0,
            "chartPreviousClose": 100.0,
            "currency": "USD",
            "fullExchangeName": "NasdaqGS",
            "regularMarketTime": NOW_OPEN,
            "currentTradingPeriod": {
                "pre": {"start": REG_START - 20000, "end": REG_START},
                "regular": {"start": REG_START, "end": REG_END},
                "post": {"start": REG_END, "end": REG_END + 14400},
            },
        },
        "timestamp": [REG_START + 100, REG_START + 200],
        "indicators": {"quote": [{
            "high": [101.0, 103.0], "low": [99.0, 100.0],
            "close": [100.5, 102.0], "volume": [1000, 2000],
        }]},
    }]}}


def test_snapshot_change_range_and_open_state():
    s = parse_quote_snapshot(_payload(), "ASML", now_epoch=NOW_OPEN)
    assert s["price"] == 102.0 and s["previous_close"] == 100.0
    assert round(s["change"], 6) == 2.0 and round(s["change_pct"], 6) == 0.02
    assert s["day_high"] == 103.0 and s["day_low"] == 99.0 and s["volume"] == 3000.0
    assert s["currency"] == "USD" and s["exchange"] == "NasdaqGS"
    assert s["market_state"] == "REGULAR" and s["delayed"] is True
    assert s["quote_time"].startswith("20")   # ISO UTC


def test_snapshot_closed_state_after_hours():
    s = parse_quote_snapshot(_payload(), "ASML", now_epoch=NOW_CLOSED)
    assert s["market_state"] == "CLOSED"


def test_snapshot_none_when_no_data():
    assert parse_quote_snapshot({"chart": {"result": []}}, "X") is None
    assert parse_quote_snapshot({}, "X") is None


def test_snapshot_uses_last_close_when_no_regular_price():
    p = _payload()
    del p["chart"]["result"][0]["meta"]["regularMarketPrice"]
    s = parse_quote_snapshot(p, "ASML", now_epoch=NOW_OPEN)
    assert s["price"] == 102.0   # último close intradía
