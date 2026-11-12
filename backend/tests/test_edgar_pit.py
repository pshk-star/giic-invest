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


IFRS_FACTS = {
    "cik": 937966,
    "facts": {"ifrs-full": {
        "Revenue": {"units": {"EUR": [
            {"start": "2025-01-01", "end": "2025-03-31", "val": 7000, "accn": "0002-20F",
             "fy": 2025, "fp": "Q1", "form": "20-F", "filed": "2025-04-15"},
        ]}},
        "DilutedEarningsLossPerShare": {"units": {"EUR/shares": [
            {"end": "2025-03-31", "val": 4.5, "accn": "0002-20F", "fy": 2025, "fp": "Q1",
             "form": "20-F", "filed": "2025-04-15"},
        ]}},
    }},
}


def test_extracts_ifrs_for_foreign_issuers():
    # Emisor extranjero (p. ej. ASML/TSM): debe capturar ifrs-full con taxonomy correcta.
    rows = extract_pit_rows(IFRS_FACTS, "ASML", 937966)
    rev = next(r for r in rows if r["concept"] == "Revenue")
    assert rev["taxonomy"] == "ifrs-full"
    assert rev["unit"] == "EUR" and rev["value"] == 7000
    assert rev["filing_date"] == "2025-04-15" and rev["form_type"] == "20-F"
    eps = next(r for r in rows if r["concept"] == "DilutedEarningsLossPerShare")
    assert eps["unit"] == "EUR/shares"


def test_usgaap_unaffected_when_no_ifrs():
    # Sin nodo ifrs-full, la salida us-gaap no cambia.
    rows = extract_pit_rows(FACTS, "MU", 723125)
    assert all(r["taxonomy"] == "us-gaap" for r in rows)


# --- P1: ingesta de componentes de capital invertido (D&A, caja, deuda, WC, acciones, goodwill) ---

CAPITAL_FACTS = {
    "cik": 100,
    "facts": {"us-gaap": {
        "DepreciationDepletionAndAmortization": {"units": {"USD": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 900, "accn": "a-10K",
             "fy": 2023, "fp": "FY", "form": "10-K", "filed": "2024-02-15"}]}},
        "AmortizationOfIntangibleAssets": {"units": {"USD": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 500, "accn": "a-10K",
             "fy": 2023, "fp": "FY", "form": "10-K", "filed": "2024-02-15"}]}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
            {"end": "2023-12-31", "val": 3000, "accn": "a-10K", "fy": 2023, "fp": "FY",
             "form": "10-K", "filed": "2024-02-15"}]}},
        "LongTermDebtCurrent": {"units": {"USD": [
            {"end": "2023-12-31", "val": 500, "accn": "a-10K", "fy": 2023, "fp": "FY",
             "form": "10-K", "filed": "2024-02-15"}]}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [
            {"start": "2023-01-01", "end": "2023-12-31", "val": 1000, "accn": "a-10K",
             "fy": 2023, "fp": "FY", "form": "10-K", "filed": "2024-02-15"}]}},
        "Goodwill": {"units": {"USD": [
            {"end": "2023-12-31", "val": 5000, "accn": "a-10K", "fy": 2023, "fp": "FY",
             "form": "10-K", "filed": "2024-02-15"}]}},
    }},
}


def test_ingesta_componentes_de_capital_invertido():
    rows = extract_pit_rows(CAPITAL_FACTS, "X", 100)
    got = {r["concept"] for r in rows}
    for c in ("DepreciationDepletionAndAmortization", "AmortizationOfIntangibleAssets",
              "CashAndCashEquivalentsAtCarryingValue", "LongTermDebtCurrent",
              "WeightedAverageNumberOfDilutedSharesOutstanding", "Goodwill"):
        assert c in got, f"falta ingerir {c}"
    # la amortización de adquisiciones queda separable de la D&A total
    dna = next(r for r in rows if r["concept"] == "DepreciationDepletionAndAmortization")
    amort = next(r for r in rows if r["concept"] == "AmortizationOfIntangibleAssets")
    assert dna["value"] == 900 and amort["value"] == 500   # D&A operativa = 900 − 500 = 400
