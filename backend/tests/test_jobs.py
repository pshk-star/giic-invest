"""Pruebas del job: construcción de filas point-in-time y orquestación (sample)."""
from app.jobs.run_scan import execute
from app.jobs.supabase_writer import build_run_row, build_snapshot_rows
from app.jobs.universe import get_universe, equity_tickers


def test_universe_is_systematic_and_nonempty():
    u = get_universe()
    assert len(u) > 50
    tickers = [i.ticker for i in u]
    assert len(tickers) == len(set(tickers))        # sin duplicados
    assert "NVDA" in tickers and "SPY" in tickers
    assert all(i.sector for i in u)                  # todos con sector (ranking sectorial)


def test_snapshot_rows_carry_point_in_time_metadata():
    scan = {
        "ranking": [
            {"rank": 1, "ticker": "AAA", "composite": 70.0,
             "factors": {"value": 60, "quality": 80, "growth": 50, "momentum": 90, "low_risk": 40},
             "tags": ["quality"], "sector": "Tech", "is_sample": True},
        ],
    }
    rows = build_snapshot_rows(scan, "run-1", "2026-11-05", "us-core-v1", "scanner-v1")
    r = rows[0]
    assert r["run_id"] == "run-1" and r["as_of"] == "2026-11-05"
    assert r["universe_version"] == "us-core-v1" and r["algo_version"] == "scanner-v1"
    assert r["ticker"] == "AAA" and r["factor_quality"] == 80


def test_run_row_captures_coverage():
    scan = {"evaluated": 10, "coverage": {"value": 0.9}, "usable_factors": ["value"],
            "excluded_insufficient_data": ["XYZ"], "weights": {"value": 0.25}}
    row = build_run_row("run-1", "2026-11-05", scan, "us-core-v1", "scanner-v1")
    assert row["evaluated"] == 10 and row["coverage"] == {"value": 0.9}
    assert row["excluded_insufficient_data"] == ["XYZ"]


def test_execute_dry_run_with_sample_provider():
    """El job corre de punta a punta sin red ni escritura (prueba de orquestación)."""
    summary = execute(provider_name="sample", top=10, dry_run=True)
    assert summary["written"] is False
    assert summary["using_sample_data"] is True
    assert summary["snapshots"] >= 1
    assert summary["evaluated"] >= 1
