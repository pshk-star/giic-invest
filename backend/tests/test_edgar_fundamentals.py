"""Pruebas de parse_companyfacts: us-gaap (USD) e ifrs-full (20-F, divisa/ADR/FX)."""
from app.providers.edgar import parse_companyfacts


def _annual(unit, pairs, form):
    return {unit: [{"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "form": form} for y, v in pairs]}


def _instant(unit, pairs, form):
    return {unit: [{"end": f"{y}-12-31", "val": v, "form": form} for y, v in pairs]}


US_FACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": {"units": _annual("USD", [(2023, 100), (2024, 120)], "10-K")},
            "NetIncomeLoss": {"units": _annual("USD", [(2023, 10), (2024, 18)], "10-K")},
            "EarningsPerShareDiluted": {"units": _annual("USD/shares", [(2023, 1.0), (2024, 1.8)], "10-K")},
            "StockholdersEquity": {"units": _instant("USD", [(2023, 50), (2024, 60)], "10-K")},
            "NetCashProvidedByUsedInOperatingActivities": {"units": _annual("USD", [(2023, 20), (2024, 30)], "10-K")},
            "PaymentsToAcquirePropertyPlantAndEquipment": {"units": _annual("USD", [(2023, 5), (2024, 8)], "10-K")},
        },
        "dei": {"EntityCommonStockSharesOutstanding": {"units": _instant("shares", [(2024, 10)], "10-K")}},
    }
}

ASML_FACTS = {  # emisor IFRS en EUR, 20-F, ADR 1:1
    "facts": {
        "ifrs-full": {
            "RevenueFromContractsWithCustomers": {"units": _annual("EUR", [(2023, 1000), (2024, 1200)], "20-F")},
            "ProfitLoss": {"units": _annual("EUR", [(2023, 200), (2024, 240)], "20-F")},
            "DilutedEarningsLossPerShare": {"units": _annual("EUR/shares", [(2023, 4.0), (2024, 5.0)], "20-F")},
            "Equity": {"units": _instant("EUR", [(2023, 500), (2024, 600)], "20-F")},
            "CashFlowsFromUsedInOperatingActivities": {"units": _annual("EUR", [(2023, 300), (2024, 360)], "20-F")},
            "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": {"units": _annual("EUR", [(2023, 50), (2024, 60)], "20-F")},
        },
        "dei": {"EntityCommonStockSharesOutstanding": {"units": _instant("shares", [(2024, 100)], "20-F")}},
    }
}


def test_usgaap_unchanged():
    f = parse_companyfacts(US_FACTS, "AAA", price=36.0)
    assert f.currency == "USD" and f.taxonomy == "us-gaap"
    assert abs(f.net_margin - 0.15) < 1e-9       # 18/120
    assert abs(f.roe - 0.30) < 1e-9              # 18/60
    assert abs(f.rev_growth_yoy - 0.20) < 1e-9
    assert abs(f.eps_growth_yoy - 0.80) < 1e-9
    assert abs(f.pe_ttm - 20.0) < 1e-9           # 36 / 1.8
    assert abs(f.market_cap - 360.0) < 1e-9      # 36 * 10
    assert abs(f.fcf_yield - (22.0 / 360.0)) < 1e-9
    assert f.as_of == "2024-12-31"


def test_ifrs_eur_with_fx_and_adr():
    f = parse_companyfacts(ASML_FACTS, "ASML", price=600.0, fx_map={"EUR": 1.1}, adr_ratio=1.0)
    assert f.currency == "EUR" and f.taxonomy == "ifrs-full"
    assert abs(f.net_margin - 0.20) < 1e-9       # 240/1200 (adimensional, EUR)
    assert abs(f.roe - 0.40) < 1e-9              # 240/600
    assert abs(f.eps_growth_yoy - 0.25) < 1e-9   # 5/4-1
    assert abs(f.pe_ttm - (600.0 / (5.0 * 1.1))) < 1e-6   # eps_usd = 5·1.1
    assert abs(f.market_cap - 60000.0) < 1e-6    # 600·100 (adr 1:1)
    assert f.fcf_yield is not None and f.fcf_yield > 0


def test_ifrs_without_fx_keeps_dimensionless_only():
    f = parse_companyfacts(ASML_FACTS, "ASML", price=600.0, fx_map={}, adr_ratio=1.0)
    assert f.currency == "EUR"
    assert f.net_margin is not None and f.roe is not None    # adimensionales OK
    assert f.pe_ttm is None and f.fcf_yield is None          # requieren FX -> None (no se fabrica)


def test_adr_ratio_scales_eps_and_market_cap():
    # ADR 5:1 (p. ej. TSM): eps_usd = eps·5·fx; market_cap = price·(shares/5).
    f1 = parse_companyfacts(ASML_FACTS, "X1", price=600.0, fx_map={"EUR": 1.0}, adr_ratio=1.0)
    f5 = parse_companyfacts(ASML_FACTS, "X5", price=600.0, fx_map={"EUR": 1.0}, adr_ratio=5.0)
    assert abs(f5.pe_ttm - f1.pe_ttm / 5.0) < 1e-6           # eps 5x mayor -> P/E 5x menor
    assert abs(f5.market_cap - f1.market_cap / 5.0) < 1e-6   # menos ADRs


# TSM-like: ifrs-full en TWD, pero EPS oficial también en USD/shares (por ADR 5:1).
TSM_FACTS = {
    "facts": {
        "ifrs-full": {
            "RevenueFromContractsWithCustomers": {"units": _annual("TWD", [(2023, 2000), (2024, 2500)], "20-F")},
            "ProfitLoss": {"units": _annual("TWD", [(2023, 800), (2024, 1000)], "20-F")},
            "Equity": {"units": _instant("TWD", [(2023, 4000), (2024, 5000)], "20-F")},
            "DilutedEarningsLossPerShare": {"units": {
                "TWD/shares": [{"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "form": "20-F"} for y, v in [(2023, 36.0), (2024, 45.0)]],
                "USD/shares": [{"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "form": "20-F"} for y, v in [(2023, 1.2), (2024, 1.5)]],
            }},
        },
        "dei": {"EntityCommonStockSharesOutstanding": {"units": _instant("shares", [(2024, 25)], "20-F")}},
    }
}


def test_tsm_prefers_official_usd_eps_no_twd_fx():
    # Sin FX de TWD: aun así el P/E se calcula con el EPS oficial en USD/shares × ADR(5).
    f = parse_companyfacts(TSM_FACTS, "TSM", price=371.0, fx_map={}, adr_ratio=5.0)
    assert f.currency == "TWD" and f.taxonomy == "ifrs-full"
    assert abs(f.net_margin - 0.40) < 1e-9          # 1000/2500 (TWD, adimensional)
    assert abs(f.roe - 0.20) < 1e-9                 # 1000/5000
    assert abs(f.eps_growth_yoy - 0.25) < 1e-9      # 45/36-1 (serie TWD)
    assert abs(f.pe_ttm - (371.0 / (1.5 * 5.0))) < 1e-6   # EPS USD 1.5 × ADR 5 = 7.5
    # market cap = precio × (acciones ordinarias / ADR) = 371 × (25/5) = 1855
    assert abs(f.market_cap - 1855.0) < 1e-6
