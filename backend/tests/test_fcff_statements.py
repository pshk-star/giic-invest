"""P1.5.1 — pruebas de la capa aditiva FCFF (fcff_statements). Puras, con fixtures companyfacts."""
from datetime import date

from app.core.connectors.fcff_statements import (
    build_edgar_fcff_fields, reconcile_ocf, check_shares_scale, integrity_report,
    fcff_eligibility, merge_recent_annual_year,
)


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


def test_reported_fields_and_quality_tags():
    facts = make_facts({
        "DepreciationDepletionAndAmortization": [(2023, 40), (2024, 48)],
        "IncomeTaxExpenseBenefit": [(2023, 30), (2024, 50)],
        "ShareBasedCompensation": [(2023, 20), (2024, 25)],
        "InterestExpense": [(2023, 5), (2024, 6)],
    })
    f = build_edgar_fcff_fields(facts, "us-gaap", "USD", CORE)
    y = f["2024-12-31"]
    assert y["dna"]["value"] == 48 and y["dna"]["quality"] == "reported"
    assert y["tax"]["value"] == 50 and y["sbc"]["value"] == 25 and y["interest"]["value"] == 6
    # pretax ausente ⇒ derivado = NI + tax ; tax_rate derivado
    assert y["pretax"]["quality"] == "derived" and y["pretax"]["value"] == 240 + 50
    assert y["tax_rate"]["quality"] == "derived" and abs(y["tax_rate"]["value"] - 50 / 290) < 1e-9


def test_missing_is_missing_not_zero():
    f = build_edgar_fcff_fields(make_facts({}), "us-gaap", "USD", CORE)
    y = f["2024-12-31"]
    assert y["dna"]["value"] is None and y["dna"]["quality"] == "missing"
    assert y["tax_rate"]["value"] is None and y["tax_rate"]["quality"] == "missing"


def test_capex_total_includes_finance_leases():
    # con leases financieros ⇒ capex_total = PP&E + lease (reported)
    facts = make_facts({"FinanceLeasePrincipalPayments": [(2024, 10)]})
    y = build_edgar_fcff_fields(facts, "us-gaap", "USD", CORE)["2024-12-31"]
    assert y["capex_total"]["value"] == 60 + 10 and y["capex_total"]["quality"] == "reported"
    # sin leases ⇒ sólo PP&E, derivado, y finance_lease marcado 'na'
    y2 = build_edgar_fcff_fields(make_facts({}), "us-gaap", "USD", CORE)["2024-12-31"]
    assert y2["capex_total"]["value"] == 60 and y2["capex_total"]["quality"] == "derived"
    assert y2["finance_lease_capex"]["quality"] == "na"


def test_wc_change_derived_from_components():
    facts = make_facts({
        "IncreaseDecreaseInAccountsReceivable": [(2024, 30)],
        "IncreaseDecreaseInInventories": [(2024, 10)],
        "IncreaseDecreaseInAccountsPayable": [(2024, 15)],
    })
    y = build_edgar_fcff_fields(facts, "us-gaap", "USD", CORE)["2024-12-31"]
    # ΔWC = -AR - inv + AP = -30 -10 +15 = -25
    assert y["wc_change"]["quality"] == "derived" and y["wc_change"]["value"] == -25


def test_reconcile_ocf_identity():
    # OCF 350 = NI 240 + D&A 48 + SBC 25 + ΔWC 37  ⇒ identidad cierra
    core = {"net_income": 240, "ocf": 350}
    extra = {"dna": {"value": 48}, "sbc": {"value": 25}, "wc_change": {"value": 37}}
    assert reconcile_ocf(core, extra)["ok"] is True
    # residual grande ⇒ no cierra
    extra_bad = {"dna": {"value": 48}, "sbc": {"value": 25}, "wc_change": {"value": -200}}
    assert reconcile_ocf(core, extra_bad)["ok"] is False


def test_check_shares_scale_guard():
    assert check_shares_scale(716.4, 199.9e9) is not None     # MCD
    assert check_shares_scale(5e4, None) is not None           # < 1e5
    assert check_shares_scale(1e9, 1e18) is not None           # precio implícito absurdo
    assert check_shares_scale(4.313e9, 413e9) is None          # KO real
    assert check_shares_scale(178e6, 0) is None                # sin mcap ⇒ sólo piso


def test_integrity_report_stale_and_recon():
    extra = build_edgar_fcff_fields(make_facts({
        "DepreciationDepletionAndAmortization": [(2024, 48)],
        "IncreaseDecreaseInOperatingCapital": [(2024, 37)],
    }), "us-gaap", "USD", CORE)
    rep = integrity_report(CORE, extra, "USD", 1e9, 50e9, today=date(2026, 11, 10), max_age_days=450)
    assert rep["currency_ok"] and rep["shares_scale_issue"] is None
    assert rep["last_period"] == "2024-12-31" and rep["stale"] is True   # >450 días


def test_fcff_eligibility_levels():
    # completo y fresco ⇒ eligible
    facts = make_facts({
        "DepreciationDepletionAndAmortization": [(2024, 48)],
        "IncomeTaxExpenseBenefit": [(2024, 50)],
        "IncreaseDecreaseInOperatingCapital": [(2024, 37)],
    })
    extra = build_edgar_fcff_fields(facts, "us-gaap", "USD", CORE)
    integ_fresh = integrity_report(CORE, extra, "USD", 1e9, 50e9, today=date(2025, 3, 1))
    elig = fcff_eligibility(CORE["2024-12-31"], extra["2024-12-31"], 1e9, integ_fresh)
    assert elig["status"] == "eligible" and not elig["missing_critical"]
    # falta D&A ⇒ degraded
    extra2 = build_edgar_fcff_fields(make_facts({"IncomeTaxExpenseBenefit": [(2024, 50)],
                                                 "IncreaseDecreaseInOperatingCapital": [(2024, 37)]}),
                                     "us-gaap", "USD", CORE)
    elig2 = fcff_eligibility(CORE["2024-12-31"], extra2["2024-12-31"], 1e9,
                             integrity_report(CORE, extra2, "USD", 1e9, 50e9, today=date(2025, 3, 1)))
    assert elig2["status"] == "degraded" and "dna" in elig2["missing_critical"]
    # escala de acciones mala ⇒ ineligible
    integ_bad = integrity_report(CORE, extra, "USD", 716.4, 199.9e9, today=date(2025, 3, 1))
    assert fcff_eligibility(CORE["2024-12-31"], extra["2024-12-31"], 716.4, integ_bad)["status"] == "ineligible"


def test_merge_tsm_eodhd_appends_fy2025_when_overlap_reconciles():
    edgar = {"2024-12-31": {"revenue": 2894, "net_income": 1157, "ocf": 1826},
             "2023-12-31": {"revenue": 2162, "net_income": 838, "ocf": 1242}}
    eodhd = {
        "revenue": {"2024-12-31": 2894, "2025-12-31": 3809},   # solape 2024 coincide
        "net_income": {"2024-12-31": 1157, "2025-12-31": 1716},
        "ocf": {"2024-12-31": 1826, "2025-12-31": 2300},
        "capex": {"2025-12-31": 1300}, "cash": {"2025-12-31": 3100}, "total_debt": {"2025-12-31": 1000},
    }
    merged, log = merge_recent_annual_year(edgar, eodhd, date(2024, 12, 31))
    assert log["appended"] == "2025-12-31" and log["state"] == "verificado"
    assert merged["2025-12-31"]["_source"] == "EODHD" and merged["2025-12-31"]["revenue"] == 3809
    assert merged["2025-12-31"]["net_debt"] == 1000 - 3100
    assert "2024-12-31" in merged and merged["2024-12-31"].get("_source") is None  # EDGAR intacto


def test_merge_flags_en_revision_on_overlap_divergence():
    edgar = {"2024-12-31": {"revenue": 2894, "net_income": 1157, "ocf": 1826}}
    eodhd = {"revenue": {"2024-12-31": 2600, "2025-12-31": 3809},  # 2024 difiere >2%
             "net_income": {"2024-12-31": 1157, "2025-12-31": 1716},
             "ocf": {"2024-12-31": 1826, "2025-12-31": 2300}}
    merged, log = merge_recent_annual_year(edgar, eodhd, date(2024, 12, 31))
    assert log["appended"] == "2025-12-31" and log["state"] == "en_revision"


def test_merge_skips_when_not_materially_posterior():
    edgar = {"2024-12-31": {"revenue": 2894}}
    eodhd = {"revenue": {"2024-12-31": 2894}}   # mismo período, no posterior
    merged, log = merge_recent_annual_year(edgar, eodhd, date(2024, 12, 31))
    assert log["appended"] is None and "2025-12-31" not in merged
