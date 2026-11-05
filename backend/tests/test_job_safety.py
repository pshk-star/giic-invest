"""Pruebas de las nuevas guardas v0.3.1: validación de publicación, bloqueo de
datos de ejemplo, fecha real de precios y harness selftest."""
from datetime import date

import pytest

from app.jobs.run_scan import ScanRejected, execute
from app.jobs.selftest import run_checks
from app.jobs.validation import newest_price_asof, validate_scan_result

TODAY = date(2026, 11, 5)


def _good_result():
    return {
        "using_sample_data": False,
        "evaluated": 20,
        "usable_factors": ["value", "quality", "growth", "momentum", "low_risk"],
        "ranking": [{"ticker": "AAA", "composite": 70.0}],
        "market_prices": {"AAA": {"close": 100.0, "as_of": "2026-11-04"}},
        "priced_count": 20,
        "fresh_fraction": 1.0,
    }


def test_valid_result_passes():
    ok, reasons = validate_scan_result(_good_result(), TODAY)
    assert ok and reasons == []


def test_sample_data_blocked():
    r = _good_result(); r["using_sample_data"] = True
    ok, reasons = validate_scan_result(r, TODAY)
    assert not ok and any("EJEMPLO" in x for x in reasons)


def test_empty_ranking_blocked():
    r = _good_result(); r["ranking"] = []
    ok, reasons = validate_scan_result(r, TODAY)
    assert not ok and any("vacío" in x for x in reasons)


def test_low_evaluated_blocked():
    r = _good_result(); r["evaluated"] = 3
    ok, reasons = validate_scan_result(r, TODAY)
    assert not ok and any("insuficientes" in x for x in reasons)


def test_no_fundamental_factors_blocked():
    r = _good_result(); r["usable_factors"] = ["momentum", "low_risk"]
    ok, reasons = validate_scan_result(r, TODAY)
    assert not ok and any("fundamentales" in x for x in reasons)


def test_stale_prices_blocked():
    r = _good_result(); r["market_prices"] = {"AAA": {"close": 1.0, "as_of": "2026-10-01"}}
    ok, reasons = validate_scan_result(r, TODAY)
    assert not ok and any("obsoletos" in x for x in reasons)


def test_missing_prices_blocked():
    r = _good_result(); r["market_prices"] = {}; r["priced_count"] = 0; r["fresh_fraction"] = 0.0
    ok, reasons = validate_scan_result(r, TODAY)
    assert not ok and any("sin precios" in x for x in reasons)


def test_newest_price_asof():
    mp = {"A": {"as_of": "2026-11-01"}, "B": {"as_of": "2026-11-04"}}
    assert newest_price_asof(mp) == "2026-11-04"
    assert newest_price_asof({}) is None


def test_production_write_blocks_sample_provider():
    """Un intento de publicar con el proveedor de ejemplo debe ser rechazado."""
    with pytest.raises(ScanRejected):
        execute(provider_name="sample", top=10, dry_run=False)


def test_prices_carry_real_data_date_not_run_date():
    """La fecha de precio proviene del dato (sample as_of = 2026-11-05), no de 'hoy'."""
    summary = execute(provider_name="sample", top=10, dry_run=True)
    # dry-run no escribe, pero validamos vía el motor que market_prices trae as_of
    from app.providers import get_provider
    from app.services.scan_engine import run_scan as eng
    from app.jobs.universe import get_universe
    res = eng(get_provider("sample"), get_universe()[:20], cache=None, today=date(2026, 12, 31), top=5)
    some = next(iter(res["market_prices"].values()))
    assert some["as_of"] == "2026-11-05"      # fecha del dato de ejemplo, no 2026-12-31


def test_selftest_harness_offline_sample():
    report = run_checks("sample")
    assert report["all_ok"] is True
    names = {c["check"] for c in report["checks"]}
    assert {"precios", "historico", "fundamentales", "fx", "scanner_validez"} <= names


def test_fresh_fraction_blocks_low_proportion():
    r = _good_result()
    r["fresh_fraction"] = 0.4           # solo 40% actualizado
    ok, reasons = validate_scan_result(r, TODAY, min_fresh_fraction=0.7)
    assert not ok and any("frescura insuficiente" in x for x in reasons)


def test_stale_instruments_excluded_from_ranking():
    """Un instrumento con precio obsoleto no debe entrar al ranking."""
    from datetime import date as _d
    from app.providers import get_provider
    from app.services.scan_engine import run_scan as eng
    from app.jobs.universe import get_universe
    # 'hoy' muy posterior a la fecha del dato de ejemplo (2026-11-05) => todo obsoleto
    res = eng(get_provider("sample"), get_universe()[:20], cache=None,
              today=_d(2027, 1, 15), top=10, max_stale_business_days=5)
    assert len(res["ranking"]) == 0            # nada fresco => ranking vacío
    assert len(res["stale_excluded"]) > 0
    assert res["fresh_fraction"] == 0.0


class _FakeWriter:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.calls = []
        self.status = []
    def insert(self, table, row):
        self.calls.append(("insert", table))
    def upsert(self, table, rows, on_conflict=None):
        self.calls.append(("upsert", table))
        if table == self.fail_on:
            raise RuntimeError("fallo simulado de red")
        return len(rows)
    def update_run_status(self, run_id, status, error=None):
        self.status.append(status)


def test_atomic_publish_marks_completed():
    from app.jobs.run_scan import publish_run
    w = _FakeWriter()
    publish_run(w, "run-1", {"id": "run-1", "status": "pending"},
                [{"run_id": "run-1", "ticker": "AAA"}],
                [{"ticker": "AAA", "close": 1.0, "as_of": "2026-11-05"}], [], [])
    assert w.status[-1] == "completed"
    assert ("insert", "scan_runs") in w.calls


def test_atomic_publish_marks_failed_on_midway_error():
    from app.jobs.run_scan import publish_run
    w = _FakeWriter(fail_on="prices")   # falla a mitad de la escritura
    with pytest.raises(RuntimeError):
        publish_run(w, "run-1", {"id": "run-1", "status": "pending"},
                    [{"run_id": "run-1", "ticker": "AAA"}],
                    [{"ticker": "AAA", "close": 1.0, "as_of": "2026-11-05"}], [], [])
    assert "completed" not in w.status
    assert w.status[-1] == "failed"
