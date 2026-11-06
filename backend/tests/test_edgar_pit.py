"""Prueba del parser PIT de EDGAR (sin red): filing_date, accession, reexpresión (/A)."""
from app.jobs.edgar_pit import extract_pit_rows

FACTS = {
    "cik": 723125,
    "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"start": "2025-03-01", "end": "2025-05-31", "val": 1000, "accn": "0000-10Q",
             "fy": 2025, "fp": "Q2", "form": "10-Q", "filed": "2025-07-01"},
            # reexpresión posterior del MISMO periodo -> otro accession, otra fila
            {"start": "2025-03-01", "end": "2025-05-31", "val": 1010, "accn": "0001-10QA",
             "fy": 2025, "fp": "Q2", "form": "10-Q/A", "filed": "2025-10-01"},
        ]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [
            {"end": "2025-05-31", "val": 1.23, "accn": "0000-10Q", "fy": 2025, "fp": "Q2",
             "form": "10-Q", "filed": "2025-07-01"},
        ]}},
    }},
}


def test_extracts_filing_date_and_accession():
    rows = extract_pit_rows(FACTS, "MU", 723125)
    rev = [r for r in rows if r["concept"] == "Revenues"]
    assert len(rev) == 2
    orig = next(r for r in rev if r["accession"] == "0000-10Q")
    amd = next(r for r in rev if r["accession"] == "0001-10QA")
    assert orig["filing_date"] == "2025-07-01" and orig["amended"] is False
    assert amd["filing_date"] == "2025-10-01" and amd["amended"] is True   # /A
    assert orig["value"] == 1000 and amd["value"] == 1010                  # no se sobrescribe
    assert orig["unit"] == "USD" and orig["period_end"] == "2025-05-31"


def test_eps_unit_and_cik():
    rows = extract_pit_rows(FACTS, "MU", 723125)
    eps = next(r for r in rows if r["concept"] == "EarningsPerShareDiluted")
    assert eps["unit"] == "USD/shares" and eps["cik"] == "723125"


def test_empty_facts():
    assert extract_pit_rows({}, "X", None) == []
