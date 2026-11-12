"""P1 — Pruebas del adaptador EDGAR -> serie del driver (puro, sin red)."""
from __future__ import annotations

from app.research.edgar_series import build_series_from_rows, _is_annual, _pick_pit


def _row(concept, value, period_end, filing_date, period_start=None, unit="USD", taxonomy="us-gaap"):
    return {"concept": concept, "value": value, "period_end": period_end, "filing_date": filing_date,
            "period_start": period_start, "unit": unit, "taxonomy": taxonomy, "fiscal_period": None,
            "accession": f"a-{concept}-{period_end}"}


def _company(years=(2021, 2022, 2023), rev0=10_000e6, growth=0.10):
    """Genera filas fundamentals_pit sintéticas de una empresa anual completa."""
    rows = []
    rev = rev0
    for y in years:
        ps, pe = f"{y}-01-01", f"{y}-12-31"
        filed = f"{y+1}-02-15"
        ebit = rev * 0.25
        rows += [
            _row("Revenues", rev, pe, filed, ps),
            _row("NetIncomeLoss", ebit * 0.80, pe, filed, ps),
            _row("OperatingIncomeLoss", ebit, pe, filed, ps),
            _row("IncomeTaxExpenseBenefit", ebit * 0.20, pe, filed, ps),
            _row("NetCashProvidedByUsedInOperatingActivities", ebit * 0.9, pe, filed, ps),
            _row("PaymentsToAcquirePropertyPlantAndEquipment", rev * 0.06, pe, filed, ps),  # positivo en EDGAR
            _row("DepreciationDepletionAndAmortization", rev * 0.09, pe, filed, ps),        # D&A total
            _row("AmortizationOfIntangibleAssets", rev * 0.05, pe, filed, ps),              # amort. adq.
            _row("WeightedAverageNumberOfDilutedSharesOutstanding", 1000e6, pe, filed, ps),
            # balance (instante: sin period_start)
            _row("StockholdersEquity", rev * 0.80, pe, filed),
            _row("CashAndCashEquivalentsAtCarryingValue", rev * 0.30, pe, filed),
            _row("LongTermDebtNoncurrent", rev * 0.20, pe, filed),
            _row("LongTermDebtCurrent", rev * 0.05, pe, filed),
            _row("AssetsCurrent", rev * 0.40, pe, filed),
            _row("LiabilitiesCurrent", rev * 0.25, pe, filed),
            _row("Goodwill", rev * 0.50, pe, filed),
            _row("FiniteLivedIntangibleAssetsNet", rev * 0.30, pe, filed),
            _row("CommonStockSharesOutstanding", 980e6, pe, filed),
        ]
        rev *= (1 + growth)
    return rows


def test_annual_detection():
    assert _is_annual("2023-01-01", "2023-12-31") is True
    assert _is_annual("2023-10-01", "2023-12-31") is False   # trimestre
    assert _is_annual(None, "2023-12-31") is False           # instante


def test_build_series_campos_basicos():
    s = build_series_from_rows(_company())
    by = s["by_field"]
    assert s["currency"] == "USD"
    assert len(by["revenue"]) == 3
    # capex con signo EODHD (negativo)
    assert all(v < 0 for v in by["capex"].values())
    # acciones diluidas preferidas (1000e6, no las 980e6 en circulación)
    assert all(abs(v - 1000e6) < 1 for v in by["shares"].values())


def test_dna_operativa_separa_amortizacion_de_adquisiciones():
    # D&A total = 9% ingresos; amort. adq. = 5% ingresos ⇒ D&A OPERATIVA = 4% ingresos
    s = build_series_from_rows(_company())
    by, meta = s["by_field"], s["meta"]
    p = sorted(by["revenue"])[0]
    rev = by["revenue"][p]
    assert abs(by["dna"][p] - rev * 0.04) < rev * 1e-6          # operativa = total − adq
    assert abs(meta[p]["dna_total"] - rev * 0.09) < rev * 1e-6
    assert abs(meta[p]["amort_acq"] - rev * 0.05) < rev * 1e-6


def test_capital_invertido_real():
    # IC = equity(0.80) + deuda total(0.20+0.05) − caja(0.30) = 0.75 × ingresos
    s = build_series_from_rows(_company())
    by = s["by_field"]
    p = sorted(by["revenue"])[0]
    rev = by["revenue"][p]
    assert abs(by["invested_capital"][p] - rev * 0.75) < rev * 1e-6
    assert abs(by["total_debt"][p] - rev * 0.25) < rev * 1e-6   # 0.20 no corriente + 0.05 corriente
    assert abs(by["equity"][p] - rev * 0.80) < rev * 1e-6


def test_wc_change_desde_corrientes():
    # WC = AC(0.40) − LC(0.25) = 0.15×ingresos; crece con los ingresos ⇒ ΔWC > 0 (uso de caja)
    s = build_series_from_rows(_company())
    by = s["by_field"]
    ps = sorted(by.get("wc_change", {}))
    assert ps, "debe haber ΔWC al menos desde el 2º año"
    assert all(v > 0 for v in by["wc_change"].values())        # WC crece con ingresos


def test_pit_toma_filing_mas_reciente_sin_lookahead():
    # misma period_end 2023, dos filings: original (2024-02) y reexpresión (2025-02)
    rows = [
        _row("Revenues", 100.0, "2023-12-31", "2024-02-15", "2023-01-01"),
        _row("Revenues", 120.0, "2023-12-31", "2025-02-15", "2023-01-01"),  # reexpresión posterior
    ]
    # sin corte: gana la reexpresión más reciente
    s_all = build_series_from_rows(rows)
    assert s_all["by_field"]["revenue"]["2023-12-31"] == 120.0
    # corte PIT en 2024-06: la reexpresión de 2025 NO existe aún ⇒ gana el original
    s_pit = build_series_from_rows(rows, as_of="2024-06-30")
    assert s_pit["by_field"]["revenue"]["2023-12-31"] == 100.0


def test_long_term_debt_total_incluye_porcion_corriente():
    # si existe LongTermDebt (total), se usa ese (+ corto), no la suma de componentes
    rows = [
        _row("Revenues", 100.0, "2023-12-31", "2024-02-15", "2023-01-01"),
        _row("StockholdersEquity", 50.0, "2023-12-31", "2024-02-15"),
        _row("CashAndCashEquivalentsAtCarryingValue", 10.0, "2023-12-31", "2024-02-15"),
        _row("LongTermDebt", 40.0, "2023-12-31", "2024-02-15"),            # total (incl. corriente)
        _row("LongTermDebtNoncurrent", 30.0, "2023-12-31", "2024-02-15"),  # componente (no debe sumarse aparte)
    ]
    s = build_series_from_rows(rows)
    assert s["by_field"]["total_debt"]["2023-12-31"] == 40.0
    assert s["by_field"]["invested_capital"]["2023-12-31"] == 50.0 + 40.0 - 10.0


def test_sin_equity_o_deuda_no_hay_capital_invertido():
    # sin balance no se inventa capital invertido (queda ausente)
    rows = [_row("Revenues", 100.0, "2023-12-31", "2024-02-15", "2023-01-01")]
    s = build_series_from_rows(rows)
    assert "invested_capital" not in s["by_field"] or "2023-12-31" not in s["by_field"].get("invested_capital", {})
