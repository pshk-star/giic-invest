"""Pruebas del enriquecimiento productivo P0.2 (orquestación + reporte). Sin red.

Cubre: clasificación/diff del reporte (nuevos/cuarentena/rechazados), compatibilidad con el payload
actual (diff vs EDGAR), y el control de costo (un vehículo ETF NO consulta EODHD)."""
import types

import app.jobs.eodhd_enrich as E


def test_classify_separa_nuevos_cuarentena_rechazados_y_diff():
    enriched = {
        "ocf": {"value": 500, "state": "parcial", "usable": True, "period": "2026-06-30",
                "currency": "USD", "filing": None, "method": None, "source": "EODHD", "edgar_state": "faltante"},
        "revenue_annual": {"value": 900, "state": "inconsistente", "usable": False, "period": "2025-12-31",
                           "currency": "USD", "filing": None, "method": None, "source": "EODHD", "edgar_state": "presente_no_vigente"},
        "cash": {"value": 10, "state": "desactualizado", "usable": False, "period": "2026-04-02",
                 "currency": "USD", "filing": None, "method": None, "source": "EODHD", "edgar_state": "presente_no_vigente"},
    }
    edgar_payload = {"ocf": None, "net_debt": 1234}   # ocf vacío en EDGAR → el enriquecido lo llena
    nuevos, cuarentena, rechazados, diffs = E.classify_enriched(enriched, edgar_payload)
    assert set(nuevos) == {"ocf"}
    assert set(cuarentena) == {"revenue_annual"}       # inconsistente → cuarentena, NUNCA en nuevos
    assert set(rechazados) == {"cash"}
    assert diffs["ocf"]["tipo"].startswith("nuevo")     # EDGAR vacío → campo nuevo
    assert diffs["ocf"]["contraparte_edgar"] == "ocf"


def test_classify_marca_complementa_cuando_edgar_presente():
    enriched = {"ocf": {"value": 500, "state": "parcial", "usable": True, "period": "2026-06-30",
                        "currency": "USD", "filing": None, "method": None, "source": "EODHD", "edgar_state": "presente_no_vigente"}}
    nuevos, _, _, diffs = E.classify_enriched(enriched, {"ocf": 480})
    assert diffs["ocf"]["tipo"].startswith("complementa")   # EDGAR presente → complementa, no reemplaza
    assert diffs["ocf"]["edgar_actual"] == 480


def test_vehiculo_etf_no_consulta_eodhd(monkeypatch):
    """Control de costo: un instrumento no_aplica (ETF) NO debe gatillar una consulta EODHD."""
    called = {"eodhd": False}

    class _Conn:
        def fetch(self, tickers, **kw):
            called["eodhd"] = True
            return {}

    class _Prov:
        _cik = {"SPY": 1}
        _client = object()
        def _facts(self, t):
            return {"facts": {"us-gaap": {}}}

    monkeypatch.setattr(E, "_submissions_recency", lambda cli, cik: (10, None, 6221))
    monkeypatch.setattr(E, "resolve_identity", lambda t: {"instrument_type": "etf"})
    fake_fund = types.SimpleNamespace(data_quality="no_aplica", instrument_class="ETF")
    monkeypatch.setattr(E, "parse_companyfacts", lambda *a, **k: fake_fund)

    out = E.enrich_one(_Prov(), _Conn(), "SPY", __import__("datetime").date(2026, 11, 7))
    assert out["status"] == "no_aplica"
    assert out["eodhd_called"] is False
    assert called["eodhd"] is False            # EODHD jamás se consultó para el vehículo


def test_sin_edgar_devuelve_estado_y_no_consulta(monkeypatch):
    class _Conn:
        def fetch(self, tickers, **kw):
            raise AssertionError("no debe consultarse")

    class _Prov:
        _cik = {}
        _client = object()
        def _facts(self, t):
            return None

    out = E.enrich_one(_Prov(), _Conn(), "ZZZZ", __import__("datetime").date(2026, 11, 7))
    assert out["status"] == "sin_edgar" and out["eodhd_called"] is False
