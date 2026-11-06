"""Pruebas del parser de histórico de precios (sin red)."""
from app.providers.yahoo import parse_yahoo_history_bars


def test_history_uses_adjclose_and_volume():
    payload = {"chart": {"result": [{
        "timestamp": [1700000000, 1700086400],
        "indicators": {
            "adjclose": [{"adjclose": [10.0, 11.0]}],
            "quote": [{"close": [10.5, 11.5], "volume": [100, 200]}],
        },
    }]}}
    bars = parse_yahoo_history_bars(payload)
    assert len(bars) == 2
    assert bars[0]["close"] == 10.0 and bars[1]["close"] == 11.0   # ajustado, no el close crudo
    assert bars[0]["volume"] == 100.0 and bars[1]["volume"] == 200.0
    assert bars[0]["as_of"].startswith("20")


def test_history_skips_null_and_handles_empty():
    payload = {"chart": {"result": [{
        "timestamp": [1700000000, 1700086400, 1700172800],
        "indicators": {"adjclose": [{"adjclose": [10.0, None, 12.0]}], "quote": [{"volume": [100, None, 300]}]},
    }]}}
    bars = parse_yahoo_history_bars(payload)
    assert len(bars) == 2 and [b["close"] for b in bars] == [10.0, 12.0]
    assert parse_yahoo_history_bars({}) == []
