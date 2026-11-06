"""Pruebas del parser de splits (sin red)."""
from app.providers.yahoo import parse_yahoo_splits


def _payload(num, den):
    return {"chart": {"result": [{"events": {"splits": {
        "1763337600": {"date": 1763337600, "numerator": num, "denominator": den,
                        "splitRatio": f"{num}:{den}"},
    }}}]}}


def test_forward_split_ratio_and_type():
    out = parse_yahoo_splits(_payload(10, 1))
    assert len(out) == 1
    assert out[0]["ratio"] == 10 and out[0]["action_type"] == "split"
    assert out[0]["numerator"] == 10 and out[0]["denominator"] == 1
    assert out[0]["ex_date"].startswith("2025-11")   # fecha efectiva (base ajustada)


def test_reverse_split_is_fraction():
    out = parse_yahoo_splits(_payload(1, 10))
    assert out[0]["ratio"] == 0.1 and out[0]["action_type"] == "reverse_split"


def test_no_events():
    assert parse_yahoo_splits({}) == []
    assert parse_yahoo_splits({"chart": {"result": [{}]}}) == []
