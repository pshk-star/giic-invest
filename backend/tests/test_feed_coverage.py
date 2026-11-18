"""P0-A (Codex): vigencia e integridad del feed de valoración gobernante.

Verifica: corrida COMPLETA marca run_kind=full y cubre todo el universo; corrida PARCIAL no reclama ser
completa ni toca a los demás; toda excepción no prevista por ticker emite una lápida no_valorable (cierra
la hipótesis D de tickers ausentes); una corrida completa publica una fila por CADA ticker del universo.
"""
import pytest
from tests.test_financial_integrity import quarters
from tests.test_valuation_engine import _series
from app.jobs import valuation_engine_run as job
from app.jobs import supabase_writer
from app.providers.edgar import EDGARProvider


class _Writer:
    def __init__(self, *a): self.pubs = []
    def select_rows(self, table, **k):
        if table == "instruments":
            return [{"ticker": t, "currency": "USD", "adr_ratio": 1} for t in job.FULL_UNIVERSE + ["AAA", "BBB", "CCC"]]
        return [{"ticker": t, "close": 50, "currency": "USD", "as_of": "2026-11-13"}
                for t in job.FULL_UNIVERSE + ["AAA", "BBB", "CCC"]]
    def publish_valuations(self, run_id, rows): self.pubs.append((run_id, rows)); return len(rows)
    def insert_append(self, *a, **k): pytest.fail("no debe usar el path legacy")


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(job, "FULL_UNIVERSE", ["AAA", "BBB", "CCC"])
    monkeypatch.setattr(EDGARProvider, "_load_ciks", lambda self: None)
    monkeypatch.setattr(EDGARProvider, "_facts", lambda self, t: None)
    monkeypatch.setattr(job, "fetch_edgar_rows", lambda *a: [])
    monkeypatch.setattr(job, "_eodhd_obj", lambda t: (_series(), quarters()))
    w = _Writer()
    monkeypatch.setattr(supabase_writer, "SupabaseWriter", lambda *a: w)
    return w


def test_full_run_marks_full_and_covers_whole_universe(_patch):
    out = job.run([], write=True, snapshot_date="2026-11-13", full=True)
    assert out["run_kind"] == "full"
    assert out["cobertura"]["error"] is None
    run_id, rows = _patch.pubs[-1]
    assert {r["ticker"] for r in rows} == {"AAA", "BBB", "CCC"}       # cubre TODO el universo
    assert all(r["payload"]["run_kind"] == "full" for r in rows)


def test_partial_run_is_marked_partial_and_scoped(_patch):
    out = job.run(["AAA"], write=True, snapshot_date="2026-11-13", full=False)
    assert out["run_kind"] == "partial"
    assert out["cobertura"]["error"] is None
    run_id, rows = _patch.pubs[-1]
    assert {r["ticker"] for r in rows} == {"AAA"}                     # NO toca BBB/CCC
    assert rows[0]["payload"]["run_kind"] == "partial"


def test_unexpected_exception_yields_tombstone_not_omission(_patch, monkeypatch):
    # Excepción NO prevista (RuntimeError) para un ticker ⇒ la guarda externa emite lápida; sin ausencias.
    real = job.evaluate_ttm
    def boom(ticker, *a, **k):
        if ticker == "BBB": raise RuntimeError("proveedor caído")
        return real(ticker, *a, **k)
    monkeypatch.setattr(job, "evaluate_ttm", boom)
    out = job.run([], write=True, snapshot_date="2026-11-13", full=True)
    run_id, rows = _patch.pubs[-1]
    assert {r["ticker"] for r in rows} == {"AAA", "BBB", "CCC"}       # BBB presente, no ausente
    bbb = next(r for r in rows if r["ticker"] == "BBB")
    assert bbb["payload"]["status"] == "no_valorable"
    assert bbb["payload"]["modelos"][0]["fair_value_usd"] is None
    assert out["cobertura"]["error"] is None                          # sigue siendo completa (lápida cuenta)


def test_full_run_never_publishes_a_partial_universe(_patch, monkeypatch):
    # Si el universo efectivo producido difiere del completo, NO se publica como completa.
    # Forzamos un universo declarado mayor que lo que la corrida puede cubrir vía instruments/prices.
    monkeypatch.setattr(job, "FULL_UNIVERSE", ["AAA", "BBB", "CCC", "ZZZ_SIN_DATOS"])
    # ZZZ no está en instruments/prices, pero la guarda igual emite una fila (lápida) ⇒ cobertura completa.
    out = job.run([], write=True, snapshot_date="2026-11-13", full=True)
    run_id, rows = _patch.pubs[-1]
    assert {r["ticker"] for r in rows} == {"AAA", "BBB", "CCC", "ZZZ_SIN_DATOS"}
    assert out["cobertura"]["error"] is None
