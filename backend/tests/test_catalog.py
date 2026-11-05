"""Pruebas del catálogo completo de instrumentos US y de la identificación desacoplada.

Cubren explícitamente TSM, ASML, NVDA, QQQ y un símbolo inválido (requisito de Pablo),
sin red: se parsean líneas de ejemplo del directorio Nasdaq Trader y se usan fakes.
"""
from datetime import date

from app.jobs.catalog import parse_catalog, parse_nasdaq_listed, parse_other_listed
from app.jobs.identify import identify_portfolio

NASDAQ_SAMPLE = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
ASML|ASML Holding N.V. - New York Registry Shares|Q|N|N|100|N|N
NVDA|NVIDIA Corporation - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|Q|N|N|100|Y|N
ZXYWTEST|Something Test Issue|Q|Y|N|100|N|N
File Creation Time: 1159202401|||||
"""

OTHER_SAMPLE = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
TSM|Taiwan Semiconductor Manufacturing Company Ltd.|N|TSM|N|100|N|TSM
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
BADT|Bad Test Issue|A|BADT|N|100|Y|
File Creation Time: 1159202401|||||
"""


def _by_ticker(rows):
    return {r["ticker"]: r for r in rows}


def test_nasdaq_listed_parses_adr_equity_and_etf():
    rows = _by_ticker(parse_nasdaq_listed(NASDAQ_SAMPLE))
    assert "ASML" in rows and rows["ASML"]["asset_class"] == "equity"
    assert rows["ASML"]["exchange"] == "NASDAQ" and rows["ASML"]["name"].startswith("ASML")
    assert rows["NVDA"]["asset_class"] == "equity"
    assert rows["QQQ"]["asset_class"] == "etf"
    assert all(r["status"] == "catalog" and r["source"] == "nasdaqtrader" for r in rows.values())


def test_other_listed_parses_nyse_adr():
    rows = _by_ticker(parse_other_listed(OTHER_SAMPLE))
    assert "TSM" in rows and rows["TSM"]["exchange"] == "NYSE" and rows["TSM"]["asset_class"] == "equity"
    assert rows["SPY"]["asset_class"] == "etf" and rows["SPY"]["exchange"] == "NYSE Arca"


def test_parser_skips_test_issues_and_trailer():
    rows = _by_ticker(parse_catalog(NASDAQ_SAMPLE, OTHER_SAMPLE))
    assert "ZXYWTEST" not in rows          # Test Issue = Y (nasdaq)
    assert "BADT" not in rows              # Test Issue = Y (other)
    assert not any(t.startswith("File") for t in rows)  # trailer excluido


def test_catalog_recognizes_the_four_required_tickers():
    rows = _by_ticker(parse_catalog(NASDAQ_SAMPLE, OTHER_SAMPLE))
    for t in ("TSM", "ASML", "NVDA", "QQQ"):
        assert t in rows, f"{t} debería estar en el catálogo"


# ---------------- Identificación + precio desacoplada ----------------

class _Quote:
    def __init__(self, price, as_of=date(2026, 11, 4), currency="USD"):
        self.price = price; self.as_of = as_of; self.currency = currency


class _FakeYahoo:
    """Resuelve TSM/ASML/NVDA/QQQ; un símbolo inválido devuelve {} y sin cotización."""
    META = {
        "TSM": {"name": "Taiwan Semiconductor", "asset_class": "equity", "currency": "USD", "exchange": "NYSE"},
        "ASML": {"name": "ASML Holding", "asset_class": "equity", "currency": "USD", "exchange": "NasdaqGS"},
        "NVDA": {"name": "NVIDIA Corp", "asset_class": "equity", "currency": "USD"},
        "QQQ": {"name": "Invesco QQQ", "asset_class": "etf", "currency": "USD"},
    }
    PRICE = {"TSM": 180.5, "ASML": 720.1, "NVDA": 195.0, "QQQ": 480.2}

    def get_instrument_meta(self, t):
        return self.META.get(t.upper(), {})

    def get_quotes(self, tickers):
        return {t: _Quote(self.PRICE[t.upper()]) for t in tickers if t.upper() in self.PRICE}


class _FakeWriter:
    def __init__(self):
        self.tables = {}
    def upsert(self, table, rows, on_conflict=None):
        self.tables.setdefault(table, []).extend(rows)
        return len(rows)


def test_identify_portfolio_resolves_valid_and_flags_invalid():
    w = _FakeWriter()
    out = identify_portfolio(w, _FakeYahoo(), ["TSM", "ASML", "NVDA", "QQQ", "ZZINVALID"])
    assert set(["TSM", "ASML", "NVDA", "QQQ"]).issubset(set(out["resolved"]))
    assert out["pending"] == ["ZZINVALID"]          # inválido: identificado como pending, nunca resolved
    assert set(["TSM", "ASML", "NVDA", "QQQ"]).issubset(set(out["priced"]))
    assert out["unpriced"] == ["ZZINVALID"]          # inválido: sin precio
    # QQQ clasificado como ETF
    inst = {r["ticker"]: r for r in w.tables["instruments"]}
    assert inst["QQQ"]["asset_class"] == "etf"
    assert inst["ZZINVALID"]["status"] == "pending" and inst["ZZINVALID"]["asset_class"] == "unknown"
