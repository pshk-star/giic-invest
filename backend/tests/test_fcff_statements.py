"""P1.5.1-A — pruebas de la capa aditiva FCFF (fcff_statements) + serie anual EODHD."""
from datetime import date

from app.core.connectors.fcff_statements import (
    build_edgar_fcff_fields, reconcile_ocf, check_shares_scale, integrity_report,
    fcff_eligibility, merge_eodhd_series, backfill_missing_dna_from_eodhd, assemble_fcff_inputs,
)
from app.core.connectors.eodhd import eodhd_annual_series_full


def ann(unit, pairs, form="10-K"):
    return {unit: [{"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "form": form} for y, v in pairs]}


def make_facts(concepts: dict) -> dict:
    return {"facts": {"us-gaap": {name: {"units": ann("USD", pairs)} for name, pairs in concepts.items()}}}


CORE = {
    "2024-12-31": {"revenue": 1200, "net_income": 240, "operating_income": 300,
                   "ocf": 350, "capex": 60, "cash": 500, "net_debt": -100},
    "2023-12-31": {"revenue": 1000, "net_income": 150, "operating_income": 200,
                   "ocf": 250, "capex": 50, "cash": 400, "net_debt": -50},
}


def test_capex_components_are_separate_not_summed():
    facts = make_facts({"FinanceLeasePrincipalPayments": [(2024, 10)],
                        "PaymentsToAcquireIntangibleAssets": [(2024, 5)]})
    y = build_edgar_fcff_fields(facts, "us-gaap", "USD", CORE)["2024-12-31"]
    assert y["capex_ppe"]["value"] == 60 and y["capex_ppe"]["quality"] == "reported"
    assert y["finance_lease_capex"]["value"] == 10 and y["finance_lease_capex"]["quality"] == "reported"
    assert y["capex_other"]["value"] == 5
    assert "capex_total" not in y  # no se auto-suma


def test_pretax_and_tax_rate_derivation_and_missing():
    y = build_edgar_fcff_fields(make_facts({"IncomeTaxExpenseBenefit": [(2024, 50)]}), "us-gaap", "USD", CORE)["2024-12-31"]
    assert y["pretax"]["quality"] == "derived" and y["pretax"]["value"] == 290
    assert abs(y["tax_rate"]["value"] - 50 / 290) < 1e-9
    y2 = build_edgar_fcff_fields(make_facts({}), "us-gaap", "USD", CORE)["2024-12-31"]
    assert y2["dna"]["quality"] == "missing" and y2["tax_rate"]["quality"] == "missing"


def test_wc_change_completeness_complete_vs_approx():
    direct = build_edgar_fcff_fields(make_facts({"IncreaseDecreaseInOperatingCapital": [(2024, 37)]}),
                                     "us-gaap", "USD", CORE)["2024-12-31"]["wc_change"]
    assert direct["quality"] == "reported" and direct["completeness"] == "complete"
    approx = build_edgar_fcff_fields(make_facts({"IncreaseDecreaseInAccountsReceivable": [(2024, 30)],
                                                 "IncreaseDecreaseInInventories": [(2024, 10)],
                                                 "IncreaseDecreaseInAccountsPayable": [(2024, 15)]}),
                                     "us-gaap", "USD", CORE)["2024-12-31"]["wc_change"]
    assert approx["quality"] == "derived" and approx["completeness"] == "approx_ar_inv_ap" and approx["value"] == -25


def test_reconcile_ocf_three_levels():
    core = {"net_income": 240, "ocf": 350}
    assert reconcile_ocf(core, {"dna": {"value": 48}, "sbc": {"value": 25}, "wc_change": {"value": 37}})["level"] == "complete"
    # residual medio (~16%) por partidas legítimas no capturadas ⇒ partial (no se rechaza)
    assert reconcile_ocf(core, {"dna": {"value": 48}, "sbc": {"value": 0}, "wc_change": {"value": 5}})["level"] == "partial"
    # residual grande ⇒ unidentified
    assert reconcile_ocf(core, {"dna": {"value": 0}, "sbc": {"value": 0}, "wc_change": {"value": -200}})["level"] == "unidentified"
    # faltan componentes ⇒ insufficient (no rechaza)
    assert reconcile_ocf(core, {"dna": {"value": None}})["level"] == "insufficient"


def test_check_shares_scale_guard():
    assert check_shares_scale(716.4, 199.9e9) is not None
    assert check_shares_scale(5e4, None) is not None
    assert check_shares_scale(4.313e9, 413e9) is None


def test_eligibility_financial_is_na():
    e = fcff_eligibility(CORE["2024-12-31"], {}, 1e9, {"shares_scale_issue": None}, is_financial=True)
    assert e["status"] == "na" and "financiera" in e["reason"]


def test_eligibility_en_revision_not_eligible():
    facts = make_facts({"DepreciationDepletionAndAmortization": [(2024, 48)],
                        "IncomeTaxExpenseBenefit": [(2024, 50)],
                        "IncreaseDecreaseInOperatingCapital": [(2024, 37)]})
    extra = build_edgar_fcff_fields(facts, "us-gaap", "USD", CORE)
    integ = integrity_report(CORE, extra, "USD", 1e9, 50e9, today=date(2025, 3, 1))
    assert fcff_eligibility(CORE["2024-12-31"], extra["2024-12-31"], 1e9, integ)["status"] == "eligible"
    assert fcff_eligibility(CORE["2024-12-31"], extra["2024-12-31"], 1e9, integ, last_state="en_revision")["status"] == "degraded"


def test_eodhd_annual_series_full_extracts_all_fields():
    obj = {"General": {"CurrencyCode": "TWD"}, "Financials": {
        "Income_Statement": {"currency_symbol": "TWD", "yearly": {
            "2025-12-31": {"date": "2025-12-31", "totalRevenue": 3809, "netIncome": 1716,
                           "operatingIncome": 1935, "incomeBeforeTax": 2030, "incomeTaxExpense": 314,
                           "interestExpense": 5},
            "2024-12-31": {"date": "2024-12-31", "totalRevenue": 2894, "netIncome": 1157,
                           "operatingIncome": 1322}}},
        "Cash_Flow": {"yearly": {
            "2025-12-31": {"totalCashFromOperatingActivities": 2300, "capitalExpenditures": -1300,
                           "depreciation": 600, "changeInWorkingCapital": 15},
            "2024-12-31": {"totalCashFromOperatingActivities": 1826, "capitalExpenditures": -960,
                           "depreciation": 540}}},
        "Balance_Sheet": {"yearly": {
            "2025-12-31": {"cash": 3100, "shortLongTermDebtTotal": 1000, "commonStockSharesOutstanding": 25.93e9}}},
    }}
    s = eodhd_annual_series_full(obj)
    assert s["currency"] == "TWD"
    bf = s["by_field"]
    assert bf["revenue"]["2025-12-31"] == 3809 and bf["dna"]["2025-12-31"] == 600
    assert bf["operating_income"]["2025-12-31"] == 1935 and bf["tax"]["2025-12-31"] == 314
    assert bf["dna"]["2024-12-31"] == 540 and bf["shares"]["2025-12-31"] == 25.93e9


def _tsm_eodhd():
    return {"currency": "TWD", "by_field": {
        "revenue": {"2024-12-31": 2894, "2025-12-31": 3809},
        "net_income": {"2024-12-31": 1157, "2025-12-31": 1716},
        "ocf": {"2024-12-31": 1826, "2025-12-31": 2300},
        "operating_income": {"2024-12-31": 1322, "2025-12-31": 1935},
        "dna": {"2024-12-31": 540, "2025-12-31": 600},
        "tax": {"2025-12-31": 314}, "pretax": {"2025-12-31": 2030},
        "capex": {"2025-12-31": -1300}, "cash": {"2025-12-31": 3100}, "total_debt": {"2025-12-31": 1000},
        "wc_change": {"2025-12-31": 15},
    }}


def test_merge_eodhd_appends_full_year_verificado_when_overlap_reconciles():
    edgar = {"2024-12-31": {"revenue": 2894, "net_income": 1157, "ocf": 1826, "operating_income": 1322}}
    merged, extra_app, log = merge_eodhd_series(edgar, _tsm_eodhd(), date(2024, 12, 31))
    assert log["appended"] == "2025-12-31" and log["state"] == "verificado"
    assert merged["2025-12-31"]["_source"] == "EODHD" and merged["2025-12-31"]["revenue"] == 3809
    assert merged["2025-12-31"]["capex"] == 1300 and merged["2025-12-31"]["net_debt"] == 1000 - 3100
    assert extra_app["dna"]["value"] == 600 and extra_app["dna"]["source"] == "EODHD"
    assert merged["2024-12-31"].get("_source") is None  # EDGAR intacto


def test_merge_en_revision_when_overlap_diverges():
    edgar = {"2024-12-31": {"revenue": 2600, "net_income": 1157, "ocf": 1826}}  # revenue difiere >3%
    _, _, log = merge_eodhd_series(edgar, _tsm_eodhd(), date(2024, 12, 31))
    assert log["state"] == "en_revision" and log["overlap"]["revenue"]["ok"] is False


def test_backfill_dna_from_eodhd_fills_only_missing():
    extra = {"2024-12-31": {"dna": {"value": None, "quality": "missing", "source": "EDGAR"}}}
    n = backfill_missing_dna_from_eodhd(extra, _tsm_eodhd())
    assert n == 1 and extra["2024-12-31"]["dna"]["value"] == 540 and extra["2024-12-31"]["dna"]["source"] == "EODHD"


def test_assemble_recovers_shares_from_eodhd_when_missing():
    hist = [CORE["2023-12-31"] | {"period_end": "2023-12-31"}, CORE["2024-12-31"] | {"period_end": "2024-12-31"}]
    eod = {"currency": "USD", "by_field": {"shares": {"2024-12-31": 1.2e9}}}
    out = assemble_fcff_inputs(make_facts({}), "us-gaap", "USD", hist, "2024-12-31", None, None,
                               eodhd_full=eod, today=date(2025, 3, 1))
    assert out["shares"] == 1.2e9 and "EODHD" in out["shares_source"]
