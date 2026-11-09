"""Pruebas del conector EODHD (E3.4) — extracción, reglas de emisión y conciliación. Sin red."""
from app.core.connectors.eodhd import (extract_eodhd, EodhdFundamentalsConnector, reconcile_quality,
                                        EODHD_FIELDS)
from app.core.connectors.registry import ProvenancedField


def _obj(ccy="EUR"):
    inc_y = {"2025-12-31": {"date": "2025-12-31", "filing_date": "2026-02-01", "totalRevenue": 28000,
                            "netIncome": 8000, "operatingIncome": 9000, "weightedAverageShsOutDil": 400}}
    inc_q = {"2026-09-30": {"date": "2026-09-30", "filing_date": "2026-10-14", "totalRevenue": 7500, "netIncome": 2100}}
    bal_y = {"2025-12-31": {"cashAndEquivalents": 5000, "longTermDebt": 4000, "shortTermDebt": 1000}}
    bal_q = {"2026-09-30": {"cashAndEquivalents": 5500, "longTermDebt": 4200, "shortTermDebt": 900}}
    cf_y = {"2025-12-31": {"totalCashFromOperatingActivities": 9000, "capitalExpenditures": 1000, "freeCashFlow": 8000}}
    cf_q = {"2026-09-30": {"totalCashFromOperatingActivities": 2500, "capitalExpenditures": 300}}
    return {"General": {"CurrencyCode": ccy}, "Highlights": {"DilutedEpsTTM": 22.0},
            "outstandingShares": {"annual": {"0": {"shares": 400}}},
            "Earnings": {"Annual": {"2025-12-31": {"date": "2025-12-31", "epsActual": 20.0}}},
            "Financials": {"Income_Statement": {"currency_symbol": ccy, "yearly": inc_y, "quarterly": inc_q},
                           "Balance_Sheet": {"yearly": bal_y, "quarterly": bal_q},
                           "Cash_Flow": {"yearly": cf_y, "quarterly": cf_q}}}


def test_extract_separa_periodos_y_bases():
    e = extract_eodhd(_obj("EUR"))
    assert e["currency"] == "EUR"
    assert e["annual"]["period_end"] == "2025-12-31" and e["interim"]["period_end"] == "2026-09-30"
    assert e["annual"]["fields"]["revenue"] == 28000 and e["interim"]["fields"]["revenue"] == 7500
    assert e["annual"]["fields"]["total_debt"] == 5000           # LT+ST
    assert e["annual"]["fields"]["fcf"] == 8000                   # provisto
    assert abs(e["interim"]["fields"]["fcf"] - (2500 - 300)) < 1e-9  # OCF−CAPEX (ambos presentes)
    assert e["eps_annual_reported"] == 20.0 and e["eps_ttm"] == 22.0


def test_fetch_emite_reglas(monkeypatch):
    c = EodhdFundamentalsConnector(api_key="DUMMY")
    monkeypatch.setattr(c, "_get", lambda sym: _obj("EUR"))
    fm = c.fetch(["ASML"])["ASML"]
    # núcleo: interino y anual como observaciones distintas
    assert "revenue" in fm and "revenue_annual" in fm
    assert fm["revenue"].period == "2026-09-30" and fm["revenue_annual"].period == "2025-12-31"
    assert fm["revenue"].currency == "EUR" and fm["revenue"].as_of == "2026-10-14"
    # regla 5: NUNCA acciones diluidas ponderadas
    assert not any("shares" in k or "diluted_shares" in k for k in fm)
    # EPS marcado como no-usar-para-valoración
    assert "NO usar para valoración" in fm["eps_annual"].method
    # capex/total_debt parciales con método explícito
    assert fm["capex_annual"].quality == "parcial" and "PP&E" in fm["capex_annual"].method
    assert "composición" in fm["total_debt_annual"].method
    # calidad base parcial
    assert fm["revenue"].quality == "parcial"


def test_fetch_fcf_no_se_fabrica_si_falta(monkeypatch):
    o = _obj("EUR")
    o["Financials"]["Cash_Flow"]["quarterly"]["2026-09-30"].pop("capitalExpenditures")
    c = EodhdFundamentalsConnector(api_key="DUMMY")
    monkeypatch.setattr(c, "_get", lambda sym: o)
    fm = c.fetch(["ASML"])["ASML"]
    assert "fcf" not in fm            # interino sin CAPEX → no se fabrica FCF
    assert "fcf_annual" in fm          # anual sí tiene ambos


def test_fetch_sin_clave_no_consulta():
    c = EodhdFundamentalsConnector(api_key="")
    assert c.fetch(["ASML"]) == {}
    assert c.available() is False


def test_reconcile_sube_verificado_y_marca_inconsistente():
    pf = lambda v, p: ProvenancedField(v, "parcial", "eodhd_fundamentals", "EODHD", period=p, currency="EUR")
    fields = {"revenue_annual": pf(28000, "2025-12-31"), "net_income_annual": pf(8000, "2025-12-31")}
    edgar = {"revenue": {"2025-12-31": 28000}, "net_income": {"2025-12-31": 6000}}
    out = reconcile_quality(fields, edgar, same_currency=True)
    assert out["revenue_annual"].quality == "verificado"          # coincide
    assert out["net_income_annual"].quality == "inconsistente"     # 8000 vs 6000 (>5%)


def test_reconcile_interino_fresco_queda_parcial():
    pf = ProvenancedField(7500, "parcial", "eodhd_fundamentals", "EODHD", period="2026-09-30", currency="EUR")
    out = reconcile_quality({"revenue_annual": pf}, {"revenue": {"2025-12-31": 28000}}, same_currency=True)
    # EDGAR no tiene 2026-09-30 → se mantiene parcial (no bloqueado): EDGAR no es el único validador
    assert out["revenue_annual"].quality == "parcial"


def test_reconcile_moneda_distinta_no_concilia():
    pf = ProvenancedField(28000, "parcial", "eodhd_fundamentals", "EODHD", period="2025-12-31", currency="USD")
    out = reconcile_quality({"revenue_annual": pf}, {"revenue": {"2025-12-31": 28000}}, same_currency=False)
    assert out["revenue_annual"].quality == "parcial"
