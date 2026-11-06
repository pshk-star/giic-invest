"""Prueba del parser FRED/ALFRED (sin red): vintages, revisiones y valores faltantes."""
from app.jobs.fred_pit import parse_fred_observations

PAYLOAD = {"observations": [
    # misma obs_date con dos vintages (revisión): deben ser dos filas
    {"realtime_start": "2026-01-15", "realtime_end": "2026-02-15", "date": "2025-12-01", "value": "258.6"},
    {"realtime_start": "2026-02-15", "realtime_end": "9999-12-31", "date": "2025-12-01", "value": "258.9"},
    # valor faltante "." -> se omite
    {"realtime_start": "2026-01-15", "realtime_end": "9999-12-31", "date": "2025-12-08", "value": "."},
    # observación normal, un solo vintage
    {"realtime_start": "2025-11-10", "realtime_end": "9999-12-31", "date": "2025-11-01", "value": "4.25"},
]}


def test_vintages_and_revisions():
    rows = parse_fred_observations(PAYLOAD, "CPIAUCSL")
    dec = [r for r in rows if r["obs_date"] == "2025-12-01"]
    assert len(dec) == 2                                  # dos vintages
    assert {r["vintage"] for r in dec} == {"2026-01-15", "2026-02-15"}
    assert {r["revision"] for r in dec} == {0, 1}         # numeradas
    assert dec[0]["value"] == 258.6 and dec[1]["value"] == 258.9
    assert all(r["release_date"] == r["vintage"] for r in rows)


def test_missing_value_skipped():
    rows = parse_fred_observations(PAYLOAD, "CPIAUCSL")
    assert not any(r["obs_date"] == "2025-12-08" for r in rows)


def test_single_vintage_series():
    rows = parse_fred_observations({"observations": [
        {"realtime_start": "2025-11-10", "realtime_end": "9999-12-31", "date": "2025-11-01", "value": "4.25"},
    ]}, "DGS10")
    assert len(rows) == 1 and rows[0]["value"] == 4.25 and rows[0]["revision"] == 0
