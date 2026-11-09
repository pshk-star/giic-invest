"""Pruebas del canary (P0.3) — candado de alcance y comparación EDGAR. Sin red."""
import app.jobs.eodhd_canary as C


def test_rechaza_tickers_fuera_del_set():
    out = C.run(commit=False, tickers=["XOM", "NVDA"])   # NVDA no está en el set canary
    assert "error" in out and "fuera del set" in out["error"]


def test_edgar_fields_equal_ignora_enrichment():
    a = {"ticker": "XOM", "pe_ttm": 10.0}
    b = {"ticker": "XOM", "pe_ttm": 10.0, "enrichment": {"fields": {"cash": {"value": 1}}}}
    assert C._edgar_fields_equal(a, b) is True             # añadir enrichment no altera EDGAR
    c = {"ticker": "XOM", "pe_ttm": 11.0, "enrichment": {}}
    assert C._edgar_fields_equal(a, c) is False            # cambiar un campo EDGAR sí difiere


def test_set_canary_es_el_autorizado():
    assert C.CANARY_SET == ["XOM", "JPM", "ASML", "TSM", "AAPL", "META"]
