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


def _row(y, v, form="10-K", filed=None):
    return {"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "form": form, "filed": filed or f"{y+1}-02-15"}


def test_period_alignment_reconstructs_ni_when_direct_tag_is_stale():
    # Caso MA: NetIncomeLoss sólo etiquetado en 2013; EPS/acciones diluidas en 2025.
    # NO debe mezclar; reconstruye NI = EPS×acciones diluidas en el período de referencia.
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_row(2024, 3000), _row(2025, 3400)]}},
        "NetIncomeLoss": {"units": {"USD": [_row(2013, 300)]}},          # obsoleto
        "EarningsPerShareDiluted": {"units": {"USD/shares": [_row(2024, 16.0), _row(2025, 17.0)]}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [_row(2024, 100), _row(2025, 100)]}},
        "StockholdersEquity": {"units": {"USD": [{"end": "2025-12-31", "val": 3400, "form": "10-K", "filed": "2026-02-15"}]}},
    }, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2025-12-31", "val": 100, "form": "10-K", "filed": "2026-02-15"}]}}}}}
    f = parse_companyfacts(facts, "MA", price=170.0)
    assert f.as_of == "2025-12-31"                 # período de referencia = EPS reciente
    assert f.ni_reconstructed is True              # NI directo (2013) NO usado
    assert abs(f.net_margin - (17.0 * 100 / 3400)) < 1e-9   # 1700/3400 = 0.5, NO el NI de 2013
    assert abs(f.pe_ttm - 10.0) < 1e-9             # 170/17
    # NI reconstruido ⇒ la consistencia NO es independiente (sería circular): no se declara.
    assert f.consistency_independent is False
    assert f.eps_consistent is None
    assert f.ni_source_concept.startswith("reconstruido")


def test_split_restatement_prefers_latest_filed_value():
    # Caso NFLX: mismo ejercicio con valor original (pre-split) y reexpresado (post-split).
    # Gana el de presentación más reciente (post-split); el crecimiento no se corrompe.
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_row(2024, 300), _row(2025, 340)]}},
        "NetIncomeLoss": {"units": {"USD": [_row(2024, 200), _row(2025, 250)]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [
            _row(2024, 20.0, filed="2025-01-20"),      # original pre-split
            _row(2024, 2.0, filed="2026-01-20"),       # reexpresado post-split (gana)
            _row(2025, 2.5, filed="2026-01-20"),
        ]}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [_row(2024, 100), _row(2025, 100)]}},
        "StockholdersEquity": {"units": {"USD": [{"end": "2025-12-31", "val": 500, "form": "10-K", "filed": "2026-02-15"}]}},
    }, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2025-12-31", "val": 100, "form": "10-K", "filed": "2026-02-15"}]}}}}}
    f = parse_companyfacts(facts, "NFLX", price=25.0)
    assert abs(f.eps_growth_yoy - 0.25) < 1e-9     # 2.5/2.0-1 (post-split), NO 2.5/20-1
    assert abs(f.pe_ttm - 10.0) < 1e-9             # 25/2.5


def test_consistency_guard_flags_eps_shares_ni_mismatch():
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_row(2025, 1000)]}},
        "NetIncomeLoss": {"units": {"USD": [_row(2025, 2000)]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [_row(2025, 10.0)]}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [_row(2025, 500)]}},
        "StockholdersEquity": {"units": {"USD": [{"end": "2025-12-31", "val": 4000, "form": "10-K", "filed": "2026-02-15"}]}},
    }, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2025-12-31", "val": 500, "form": "10-K", "filed": "2026-02-15"}]}}}}}
    f = parse_companyfacts(facts, "BAD", price=100.0)
    assert f.ni_reconstructed is False             # NI directo presente en el período
    assert f.consistency_independent is True       # compara NI REPORTADO vs EPS×acciones (independiente)
    assert f.eps_consistent is False               # 10×500/2000 = 2.5 ≠ 1
    assert abs(f.eps_check_ratio - 2.5) < 1e-9
    assert f.ni_source_concept == "NetIncomeLoss"  # procedencia reportada


def test_eps_ttm_is_split_invariant_via_quarterly_net_income():
    from datetime import date
    from app.providers.edgar import eps_ttm_from_quarterly_ni
    # 4 trimestres de utilidad neta (montos absolutos, invariantes al split): 250+260+270+280=1060
    q = [(date(2025, 1, 1), date(2025, 3, 31), 250.0, date(2025, 4, 20)),
         (date(2025, 4, 1), date(2025, 6, 30), 260.0, date(2025, 7, 20)),
         (date(2025, 7, 1), date(2025, 9, 30), 270.0, date(2025, 10, 20)),
         (date(2025, 10, 1), date(2025, 12, 31), 280.0, date(2026, 1, 20))]
    pre = eps_ttm_from_quarterly_ni(q, diluted_shares=100.0)    # antes del split 10:1
    post = eps_ttm_from_quarterly_ni(q, diluted_shares=1000.0)  # acciones vigentes post-split
    assert abs(pre["eps_ttm"] - 10.6) < 1e-9       # 1060/100
    assert abs(post["eps_ttm"] - 1.06) < 1e-9      # 1060/1000 (NI dólar invariante / acciones vigentes)
    assert pre["ni_ttm"] == 1060.0 and post["ni_ttm"] == 1060.0


def test_eps_ttm_rejects_incomplete_or_overlapping_quarters():
    from datetime import date
    from app.providers.edgar import eps_ttm_from_quarterly_ni
    assert eps_ttm_from_quarterly_ni([], 100.0) is None
    q3 = [(date(2025, 1, 1), date(2025, 3, 31), 250.0, date(2025, 4, 20)),
          (date(2025, 4, 1), date(2025, 6, 30), 260.0, date(2025, 7, 20)),
          (date(2025, 7, 1), date(2025, 9, 30), 270.0, date(2025, 10, 20))]
    assert eps_ttm_from_quarterly_ni(q3, 100.0) is None            # sólo 3 trimestres
    gap = q3 + [(date(2026, 4, 1), date(2026, 6, 30), 280.0, date(2026, 7, 20))]  # hueco (falta Q4 2025)
    assert eps_ttm_from_quarterly_ni(gap, 100.0) is None


def test_yahoo_fallback_used_only_when_edgar_lacks_eps():
    # Caso Visa: EDGAR sin EPS → se usa el EPS TTM de Yahoo (USD), etiquetado por fuente/base.
    no_eps = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_row(2025, 45000)]}},
        "NetIncomeLoss": {"units": {"USD": [_row(2025, 23000)]}},
        # sin EarningsPerShareDiluted/Basic ni acciones ponderadas (como Visa)
    }, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2010-01-27", "val": 469, "form": "10-K", "filed": "2010-02-03"}]}}}}}
    fb = {"eps_ttm": 10.5, "shares": 1900, "currency": "USD", "as_of": "2026-11-06", "source": "yahoo:quote"}
    f = parse_companyfacts(no_eps, "V", price=420.0, fallback=fb)
    assert f.eps is not None and abs(f.eps - 10.5) < 1e-9     # EPS de Yahoo (EDGAR no tenía)
    assert f.eps_source == "yahoo:quote" and f.eps_basis == "ttm"
    assert abs(f.pe_ttm - (420.0 / 10.5)) < 1e-9
    assert f.shares_source == "yahoo:quote:shares"           # portada 2010 obsoleta → Yahoo
    assert "eps_ttm<-yahoo:quote" in (f.fallback_sources or "")


def test_fallback_never_overwrites_edgar_and_respects_currency():
    # Con EPS de EDGAR presente, el fallback NO se usa (no sobrescribe lo oficial).
    f = parse_companyfacts(US_FACTS, "AAA", price=36.0,
                           fallback={"eps_ttm": 99.0, "shares": 999, "currency": "USD", "source": "yahoo:quote"})
    assert f.eps_source == "edgar" and abs(f.pe_ttm - 20.0) < 1e-9   # 36/1.8, no 36/99
    # Moneda incoherente (no USD) → no se usa aunque falte EPS.
    no_eps = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [_row(2025, 100)]}}}}}
    g = parse_companyfacts(no_eps, "X", price=50.0,
                           fallback={"eps_ttm": 5.0, "currency": "EUR", "source": "yahoo:quote"})
    assert g.eps is None and g.pe_ttm is None                # EUR ≠ USD → no se fabrica


def _q(unit, quarters, form="10-Q"):
    return {unit: [{"start": s, "end": e, "val": v, "form": form, "filed": e} for s, e, v in quarters]}


_Q25 = [("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30"),
        ("2025-07-01", "2025-09-30"), ("2025-10-01", "2025-12-31")]


def _ytd(unit, start, end, val, form="10-Q"):
    return {"start": start, "end": end, "val": val, "form": form, "filed": end}


def test_eps_ttm_rolling_identity_and_fcf_ttm_and_net_debt():
    # Identidad rodante: TTM(2026-09-30) = YTD_9m_2026 + FY2025 − YTD_9m_2025.
    # EPS: 3.6 + 4.4 − 3.3 = 4.7 ; FCF OCF: 400+500−360=540, CAPEX: 80+100−70=110 → FCF_TTM=430.
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_row(2024, 1800), _row(2025, 2000)]}},
        "NetIncomeLoss": {"units": {"USD": [_row(2024, 400), _row(2025, 440),
            _ytd("USD", "2025-01-01", "2025-09-30", 330), _ytd("USD", "2026-01-01", "2026-09-30", 360)]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [_row(2024, 4.0), _row(2025, 4.4),
            _ytd("USD/shares", "2025-01-01", "2025-09-30", 3.3), _ytd("USD/shares", "2026-01-01", "2026-09-30", 3.6)]}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [_row(2025, 100)]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [_row(2025, 500),
            _ytd("USD", "2025-01-01", "2025-09-30", 360), _ytd("USD", "2026-01-01", "2026-09-30", 400)]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [_row(2025, 100),
            _ytd("USD", "2025-01-01", "2025-09-30", 70), _ytd("USD", "2026-01-01", "2026-09-30", 80)]}},
        "GrossProfit": {"units": {"USD": [_row(2025, 1200)]}},
        "OperatingIncomeLoss": {"units": {"USD": [_row(2025, 600)]}},
        "StockholdersEquity": {"units": {"USD": [{"end": "2025-12-31", "val": 2200, "form": "10-K", "filed": "2026-02-15"}]}},
        "LongTermDebtNoncurrent": {"units": {"USD": [{"end": "2025-12-31", "val": 1000, "form": "10-K", "filed": "2026-02-15"}]}},
        "LongTermDebtCurrent": {"units": {"USD": [{"end": "2025-12-31", "val": 200, "form": "10-K", "filed": "2026-02-15"}]}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [{"end": "2025-12-31", "val": 300, "form": "10-K", "filed": "2026-02-15"}]}},
    }, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2025-12-31", "val": 100, "form": "10-K", "filed": "2026-02-15"}]}}}}}
    f = parse_companyfacts(facts, "QQ", price=47.0)
    assert abs(f.eps_ttm - 4.7) < 1e-9 and "YTD" in (f.eps_ttm_window or "")
    assert abs(f.eps_annual - 4.4) < 1e-9
    assert f.eps_basis == "ttm" and abs(f.pe_ttm - 10.0) < 1e-9          # usa TTM 4.7
    assert abs(f.ttm_vs_annual_ratio - (4.7 / 4.4)) < 1e-3               # redondeado a 4 decimales
    assert abs(f.fcf_annual - 400.0) < 1e-9 and abs(f.fcf_ttm - 430.0) < 1e-9
    assert abs(f.gross_debt - 1200.0) < 1e-9 and abs(f.net_debt - 900.0) < 1e-9
    assert abs(f.gross_margin - 0.6) < 1e-9 and abs(f.operating_margin - 0.3) < 1e-9
    assert abs(f.diluted_shares - 100.0) < 1e-9


def test_ttm_equals_annual_when_no_newer_interim():
    from app.providers.edgar import ttm_flow
    rows = [_row(2024, 4.0, filed="2025-02-15"), _row(2025, 4.4, filed="2026-02-15")]
    t = ttm_flow(rows)
    assert t["window"] == "anual" and abs(t["ttm"] - 4.4) < 1e-9


def test_e31_ttm_igual_a_anual_cuando_no_hay_trimestre_posterior():
    # E3.1: sin interino posterior al cierre, el TTM debe exponerse = EPS/FCF anual reportado
    # (idénticos por definición), con window="anual" y usando la cifra oficial, no re-derivada.
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_row(2024, 1800), _row(2025, 2000)]}},
        "NetIncomeLoss": {"units": {"USD": [_row(2024, 400), _row(2025, 440)]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [_row(2024, 4.0), _row(2025, 4.4)]}},
        "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": {"shares": [_row(2025, 100)]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [_row(2024, 460), _row(2025, 500)]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [_row(2024, 90), _row(2025, 100)]}},
        "StockholdersEquity": {"units": {"USD": [{"end": "2025-12-31", "val": 2200, "form": "10-K", "filed": "2026-02-15"}]}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [{"end": "2025-12-31", "val": 300, "form": "10-K", "filed": "2026-02-15"}]}},
    }, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2025-12-31", "val": 100, "form": "10-K", "filed": "2026-02-15"}]}}}}}
    f = parse_companyfacts(facts, "QQ", price=44.0)
    assert f.eps_ttm_window == "anual"
    assert abs(f.eps_ttm - 4.4) < 1e-9 and abs(f.eps_ttm - f.eps_annual) < 1e-12   # = anual reportado
    assert abs(f.ttm_vs_annual_ratio - 1.0) < 1e-9
    assert abs(f.fcf_annual - 400.0) < 1e-9 and abs(f.fcf_ttm - 400.0) < 1e-9       # FCF TTM = anual
    assert f.eps_basis == "ttm" and abs(f.pe_ttm - 10.0) < 1e-9


def test_ttm_split_uses_restated_comparatives():
    from app.providers.edgar import ttm_flow
    # EPS por acción con split: el YTD previo y el anual previo vienen REEXPRESADOS (filed reciente).
    rows = [
        _row(2025, 2.0, filed="2026-02-15"),                                       # FY2025 anual (post-split)
        {"start": "2025-01-01", "end": "2025-09-30", "val": 15.0, "form": "10-Q", "filed": "2025-10-20"},  # YTD9m 2025 original pre-split
        {"start": "2025-01-01", "end": "2025-09-30", "val": 1.5, "form": "10-Q", "filed": "2026-10-20"},   # YTD9m 2025 reexpresado (gana)
        {"start": "2026-01-01", "end": "2026-09-30", "val": 1.8, "form": "10-Q", "filed": "2026-10-20"},   # YTD9m 2026
    ]
    t = ttm_flow(rows)
    # TTM(2026-09-30) = 1.8 + 2.0 − 1.5 = 2.3 (usa el YTD previo REEXPRESADO 1.5, NO el 15.0 original)
    assert "YTD" in t["window"] and abs(t["ttm"] - 2.3) < 1e-9


def test_detect_eps_split_mixing_flags_crossing_a_split():
    from datetime import date
    from app.providers.edgar import detect_eps_split_mixing
    pts = [(date(2024, 12, 31), 19.83), (date(2025, 12, 31), 2.53)]
    assert detect_eps_split_mixing(pts, [date(2025, 11, 17)]) is True   # el split cae dentro del rango
    assert detect_eps_split_mixing(pts, [date(2020, 1, 1)]) is False    # split anterior a la serie
    assert detect_eps_split_mixing(pts, []) is False


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


def test_has_annual_core_discrimina_emisor_real_de_homonima_vacia():
    from app.providers.edgar import _has_annual_core
    real = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": _annual("USD", [(2024, 18)], "10-K")}}}}
    # Entidad homónima: declara la CLAVE pero SIN valores anuales (solo un trimestre suelto).
    vacia = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
        {"start": "2024-07-01", "end": "2024-09-30", "val": 1, "form": "10-Q"}]}}}}}
    assert _has_annual_core(real) is True
    assert _has_annual_core(vacia) is False


def test_facts_resuelve_colision_ticker_cik_elige_emisor_con_datos():
    """XOM-style: una sigla mapea a dos CIK; se elige la que tiene series anuales reales."""
    from app.providers.edgar import EDGARProvider
    REAL_CIK, EMPTY_CIK = 34088, 2115436
    tickers_json = {
        "0": {"cik_str": EMPTY_CIK, "ticker": "XOM", "title": "Homonima Reciente"},  # 'última gana' tomaría esta
        "1": {"cik_str": REAL_CIK, "ticker": "XOM", "title": "Exxon Mobil"},
    }
    facts_real = {"facts": {"us-gaap": {
        "Revenues": {"units": _annual("USD", [(2023, 300000), (2024, 340000)], "10-K")},
        "NetIncomeLoss": {"units": _annual("USD", [(2023, 36000), (2024, 33000)], "10-K")}}}}
    facts_empty = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
        {"start": "2024-07-01", "end": "2024-09-30", "val": 5, "form": "10-Q"}]}}}}}

    class _Resp:
        def __init__(self, code, payload): self.status_code = code; self._p = payload
        def json(self): return self._p
        def raise_for_status(self):
            if self.status_code != 200: raise RuntimeError(self.status_code)

    class _Client:
        def get(self, url):
            if "company_tickers" in url: return _Resp(200, tickers_json)
            if f"CIK{REAL_CIK:010d}" in url: return _Resp(200, facts_real)
            if f"CIK{EMPTY_CIK:010d}" in url: return _Resp(200, facts_empty)
            return _Resp(404, {})

    prov = EDGARProvider.__new__(EDGARProvider)   # evita import httpx del __init__ (no en sandbox)
    prov.retries = 1
    prov._cik, prov._cik_cands = {}, {}
    prov._client = _Client()
    facts = prov._facts("XOM")
    assert facts is facts_real                       # eligió el emisor real, no la 'última gana'
    assert prov._cik["XOM"] == REAL_CIK              # CIK corregida y cacheada (la usan _sic/edgar_pit)


def test_facts_fallback_browse_edgar_cuando_tickers_json_apunta_a_entidad_vacia():
    """XOM real: tickers.json mapea XOM→2115436 (sin serie anual); el filer con 10-K es 34088."""
    from app.providers.edgar import EDGARProvider
    EMPTY_CIK, REAL_CIK = 2115436, 34088
    tickers_json = {"0": {"cik_str": EMPTY_CIK, "ticker": "XOM", "title": "Entidad sin datos"}}
    facts_empty = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
        {"start": "2024-07-01", "end": "2024-09-30", "val": 5, "form": "10-Q"}]}}}}}
    facts_real = {"entityName": "Exxon Mobil Corporation", "facts": {"us-gaap": {
        "Revenues": {"units": _annual("USD", [(2024, 340000), (2025, 345000)], "10-K")},
        "NetIncomeLoss": {"units": _annual("USD", [(2024, 33000), (2025, 34000)], "10-K")}}}}
    atom = f"<feed><company-info><cik>{REAL_CIK}</cik></company-info></feed>"

    class _Resp:
        def __init__(self, code, payload=None, text=""): self.status_code = code; self._p = payload; self.text = text
        def json(self): return self._p
        def raise_for_status(self):
            if self.status_code != 200: raise RuntimeError(self.status_code)

    class _Client:
        def get(self, url):
            if "company_tickers" in url: return _Resp(200, tickers_json)
            if "browse-edgar" in url: return _Resp(200, text=atom)
            if f"CIK{REAL_CIK:010d}" in url: return _Resp(200, facts_real)
            if f"CIK{EMPTY_CIK:010d}" in url: return _Resp(200, facts_empty)
            return _Resp(404, {})

    prov = EDGARProvider.__new__(EDGARProvider)
    prov.retries = 1
    prov._cik, prov._cik_cands = {}, {}
    prov._client = _Client()
    facts = prov._facts("XOM")
    assert facts is facts_real                      # usó el filer real 34088, no la entidad vacía
    assert prov._cik["XOM"] == REAL_CIK             # CIK corregida y cacheada
