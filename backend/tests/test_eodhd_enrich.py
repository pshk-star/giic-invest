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


# --- P0.3: anotación de valoración, esquema y hook de escritura aislado ---

def test_annotate_valuation_por_periodo():
    enriched = {
        "revenue": {"value": 100, "state": "parcial", "usable": True},        # trimestre → no apto
        "revenue_annual": {"value": 400, "state": "parcial", "usable": True},  # anual → apto
        "cash": {"value": 50, "state": "parcial", "usable": True},             # balance → apto
        "eps_ttm": {"value": 5, "state": "parcial", "usable": True},           # ttm pero ambiguo → no
    }
    pt = {"revenue": "trimestre_individual", "revenue_annual": "anual",
          "cash": "balance_instantaneo", "eps_ttm": "ttm"}
    out = E.annotate_valuation(enriched, pt)
    assert out["revenue"]["valuation_eligible"] is False and "valuation_note" in out["revenue"]
    assert out["revenue_annual"]["valuation_eligible"] is True
    assert out["cash"]["valuation_eligible"] is True
    assert out["eps_ttm"]["valuation_eligible"] is False     # EPS base ambigua


def test_build_enrichment_block_esquema_completo():
    enriched = {"ocf": {"value": 500, "currency": "EUR", "source": "EODHD (ASML.AS)", "period": "2026-09-30",
                        "period_type": "ytd_acumulado", "state": "parcial", "usable": True,
                        "valuation_eligible": False, "valuation_note": "YTD"}}
    blk = E.build_enrichment_block("ASML", "ASML.AS", "EUR", "2025-12-31", enriched)
    f = blk["fields"]["ocf"]
    for key in ("value", "currency", "source", "symbol", "period_end", "period_type",
                "quality_state", "valuation_eligible"):
        assert key in f, key
    assert blk["schema_version"] and blk["symbol"] == "ASML.AS"


def test_attach_enrichment_aditivo_no_toca_edgar():
    edgar = {"ticker": "ASML", "pe_ttm": 30.0, "net_debt": 1000, "currency": "EUR"}
    blk = {"schema_version": "x", "fields": {"ocf": {"value": 500}}}
    out = E.attach_enrichment(edgar, blk, enabled=True)
    # campos EDGAR intactos + bloque aditivo
    assert out["pe_ttm"] == 30.0 and out["net_debt"] == 1000 and out["currency"] == "EUR"
    assert out["enrichment"]["fields"]["ocf"]["value"] == 500
    # el payload original no se mutó
    assert "enrichment" not in edgar


def test_attach_enrichment_idempotente():
    edgar = {"ticker": "ASML", "pe_ttm": 30.0}
    blk = {"schema_version": "x", "fields": {"ocf": {"value": 500}}}
    once = E.attach_enrichment(edgar, blk)
    twice = E.attach_enrichment(once, blk)       # re-aplicar no duplica ni cambia EDGAR
    assert twice == once


def test_attach_enrichment_failsafe_desactivado():
    edgar = {"ticker": "ASML", "pe_ttm": 30.0}
    blk = {"schema_version": "x", "fields": {"ocf": {"value": 500}}}
    out = E.attach_enrichment(edgar, blk, enabled=False)
    assert "enrichment" not in out and out == edgar   # sin clave/desactivado → EDGAR intacto


def test_attach_enrichment_bloque_vacio_no_escribe():
    edgar = {"ticker": "ASML", "pe_ttm": 30.0}
    out = E.attach_enrichment(edgar, {"schema_version": "x", "fields": {}}, enabled=True)
    assert "enrichment" not in out            # nada usable → no se añade bloque


def test_attach_enrichment_serializa_json():
    import json
    edgar = {"ticker": "ASML", "pe_ttm": 30.0}
    blk = {"schema_version": "x", "fields": {"ocf": {"value": 500, "period_type": "ytd_acumulado"}}}
    out = E.attach_enrichment(edgar, blk)
    s = json.dumps(out)                        # persistible como JSON (como Supabase payload)
    assert json.loads(s)["enrichment"]["fields"]["ocf"]["period_type"] == "ytd_acumulado"


# --- P0.3-final: gate por disponibilidad, carry-forward y orquestador ---

def test_should_query_eodhd_por_disponibilidad():
    todos_vigentes = {k: "vigente" for k in E.GATE_FIELDS}
    assert E.should_query_eodhd(todos_vigentes) is False          # EDGAR suficiente → no consultar
    falta_uno = dict(todos_vigentes); falta_uno["capex"] = "faltante"
    assert E.should_query_eodhd(falta_uno) is True                # falta un campo → consultar
    no_aplica = dict(todos_vigentes); no_aplica["net_debt"] = "no_aplica"
    assert E.should_query_eodhd(no_aplica) is False               # no_aplica no obliga a consultar


def test_carry_forward_preserva_bloque_previo():
    edgar = {"ticker": "ASML", "pe_ttm": 30.0}
    prev = {"schema_version": "p0.3-1", "fields": {"cash": {"value": 8e9}}}
    # sin bloque fresco pero con previo → se conserva, marcado carried_forward
    out = E.attach_enrichment(edgar, None, enabled=True, prev_block=prev)
    assert out["enrichment"]["carried_forward"] is True
    assert out["enrichment"]["fields"]["cash"]["value"] == 8e9
    assert out["pe_ttm"] == 30.0                                  # EDGAR intacto


def test_fresco_sobrescribe_previo_sin_carry_flag():
    edgar = {"ticker": "ASML"}
    prev = {"schema_version": "p0.3-1", "fields": {"cash": {"value": 1}}}
    fresh = {"schema_version": "p0.3-1", "fields": {"cash": {"value": 2}}}
    out = E.attach_enrichment(edgar, fresh, enabled=True, prev_block=prev)
    assert out["enrichment"]["fields"]["cash"]["value"] == 2
    assert "carried_forward" not in out["enrichment"]


def test_enrich_scan_payloads_failsafe_sin_clave(monkeypatch):
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    payloads = {"AAPL": {"ticker": "AAPL", "pe_ttm": 30.0}}
    s = E.enrich_scan_payloads(payloads, ["AAPL"], enabled=True)
    assert payloads["AAPL"] == {"ticker": "AAPL", "pe_ttm": 30.0}  # intacto (fail-safe)
    assert "fail_safe" in s


def test_enrich_scan_payloads_enriquece_y_preserva(monkeypatch):
    monkeypatch.setenv("EODHD_API_KEY", "k")
    monkeypatch.setenv("EDGAR_USER_AGENT", "x@y.com")
    monkeypatch.setattr(E, "EDGARProvider", lambda **k: object())
    monkeypatch.setattr(E, "EodhdFundamentalsConnector", lambda **k: object())
    block = {"schema_version": "p0.3-1", "fields": {"ocf": {"value": 500, "period_type": "trimestre_individual"}}}
    monkeypatch.setattr(E, "enrich_one", lambda prov, conn, t, d: {"status": "ok", "eodhd_called": True, "enrichment_block": block})
    payloads = {"ASML": {"ticker": "ASML", "pe_ttm": 30.0}}
    s = E.enrich_scan_payloads(payloads, ["ASML"], enabled=True)
    assert payloads["ASML"]["enrichment"]["fields"]["ocf"]["value"] == 500
    assert payloads["ASML"]["pe_ttm"] == 30.0                     # EDGAR intacto
    assert s["enriquecidos"] == 1


def test_enrich_scan_payloads_edgar_suficiente_conserva_previo(monkeypatch):
    monkeypatch.setenv("EODHD_API_KEY", "k")
    monkeypatch.setenv("EDGAR_USER_AGENT", "x@y.com")
    monkeypatch.setattr(E, "EDGARProvider", lambda **k: object())
    monkeypatch.setattr(E, "EodhdFundamentalsConnector", lambda **k: object())
    monkeypatch.setattr(E, "enrich_one", lambda prov, conn, t, d: {"status": "edgar_suficiente", "eodhd_called": False})
    prev = {"ASML": {"ticker": "ASML", "enrichment": {"schema_version": "p0.3-1", "fields": {"cash": {"value": 9}}}}}
    payloads = {"ASML": {"ticker": "ASML", "pe_ttm": 30.0}}
    s = E.enrich_scan_payloads(payloads, ["ASML"], prev_payloads=prev, enabled=True)
    assert payloads["ASML"]["enrichment"]["carried_forward"] is True   # no se borra el bloque previo
    assert s["carry_forward"] == 1


def test_build_block_separa_cuarentena():
    enriched = {
        "cash": {"value": 50, "currency": "USD", "source": "EODHD", "period": "2026-09-30",
                 "period_type": "balance_instantaneo", "state": "parcial", "usable": True, "valuation_eligible": True},
        "revenue_annual": {"value": 900, "currency": "USD", "source": "EODHD", "period": "2025-12-31",
                           "period_type": "anual", "state": "inconsistente", "usable": False, "valuation_eligible": False},
    }
    blk = E.build_enrichment_block("JPM", "JPM.US", "USD", "2026-09-30", enriched)
    assert "cash" in blk["fields"] and "revenue_annual" not in blk["fields"]
    assert "revenue_annual" in blk["quarantine"]          # inconsistente → cuarentena, nunca en fields
    assert blk["quarantine"]["revenue_annual"]["quality_state"] == "inconsistente"
    assert "valuation_eligible_meaning" in blk            # aclara elegible != verificado


# --- P0.3-write: preservación del bloque en la capa de escritura (carry-forward independiente del flag) ---

def test_preserve_enrichment_blocks_rescan_edgar_only():
    # Payload nuevo EDGAR-only (sin enrichment) + previo CON bloque → se arrastra (carry-forward).
    payloads = {"XOM": {"ticker": "XOM", "pe_ttm": 10.0}}   # recién recalculado, sin enrichment
    prev = {"XOM": {"ticker": "XOM", "pe_ttm": 9.0, "enrichment": {"fields": {"cash": {"value": 1}}}}}
    n = E.preserve_enrichment_blocks(payloads, prev)
    assert n == 1
    assert payloads["XOM"]["enrichment"]["carried_forward"] is True
    assert payloads["XOM"]["enrichment"]["fields"]["cash"]["value"] == 1
    assert payloads["XOM"]["pe_ttm"] == 10.0               # EDGAR nuevo intacto


def test_preserve_no_pisa_bloque_fresco():
    payloads = {"XOM": {"ticker": "XOM", "enrichment": {"fields": {"cash": {"value": 2}}}}}  # ya trae fresco
    prev = {"XOM": {"enrichment": {"fields": {"cash": {"value": 1}}}}}
    n = E.preserve_enrichment_blocks(payloads, prev)
    assert n == 0                                          # no se sobrescribe el bloque fresco
    assert payloads["XOM"]["enrichment"]["fields"]["cash"]["value"] == 2


def test_preserve_sin_previo_no_inventa():
    payloads = {"AAPL": {"ticker": "AAPL", "pe_ttm": 30.0}}
    n = E.preserve_enrichment_blocks(payloads, {})
    assert n == 0 and "enrichment" not in payloads["AAPL"]
