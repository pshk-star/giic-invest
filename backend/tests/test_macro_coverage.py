"""Prueba de la ventana PIT (restricción de vintage, no intersección de fechas)."""
from app.research.macro_coverage import pit_window


def test_binding_is_latest_vintage():
    by = {
        "CPI": [{"obs_date": "1960-01-01", "value": 1, "vintage": "1972-01-01"},
                {"obs_date": "2020-01-01", "value": 2, "vintage": "2020-01-15"}],
        "DGS10": [{"obs_date": "1962-01-02", "value": 3, "vintage": "1962-01-02"},
                  {"obs_date": "2020-01-02", "value": 4, "vintage": "2020-01-02"}],
        "NFCI": [{"obs_date": "1971-01-08", "value": 5, "vintage": "2011-05-25"},
                 {"obs_date": "2020-01-03", "value": 6, "vintage": "2020-01-03"}],
    }
    # con las 3: la vinculante es NFCI (vintage 2011) -> inicio 2011
    w_all = pit_window(by, ["CPI", "DGS10", "NFCI"])
    assert w_all["start"] == "2011-05-25" and w_all["binding_series"] == "NFCI"
    # sin NFCI: la vinculante es CPI (1972) -> inicio 1972
    w_long = pit_window(by, ["CPI", "DGS10"])
    assert w_long["start"] == "1972-01-01" and w_long["binding_series"] == "CPI"
    assert w_long["years"] > w_all["years"]


def test_missing_series_returns_none():
    w = pit_window({"CPI": [{"obs_date": "1960-01-01", "value": 1, "vintage": "1972-01-01"}]},
                   ["CPI", "ZZZ"])
    assert w["start"] is None and w["binding_series"] == "ZZZ"
