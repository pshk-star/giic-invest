"""Pruebas de la reconstrucción TTM (puras): FY + YTD − YTD_prev, emparejamiento estricto, capex de fuentes."""
from __future__ import annotations

from app.research.ttm import ttm_edgar, _edgar_periods, reconstruct_ttm


def _row(concept, val, ps, pe, filed):
    return {"concept": concept, "unit": "USD", "value": val, "period_start": ps, "period_end": pe, "filing_date": filed}


def _nvda_ocf_rows():
    C = "NetCashProvidedByUsedInOperatingActivities"
    return [
        _row(C, 102.7e9, "2025-01-27", "2026-01-25", "2026-02-25"),   # FY2026
        _row(C, 42.8e9, "2025-01-27", "2025-07-27", "2025-08-26"),    # 6M FY2026 (comparable)
        _row(C, 74.4e9, "2026-01-26", "2026-07-26", "2026-08-26"),    # 6M FY2027 (actual)
    ]


def test_ttm_edgar_fy_mas_ytd_menos_ytd_prev():
    # TTM OCF = 102.7 + 74.4 − 42.8 = 134.3B  (caso NVDA real)
    val, meta = ttm_edgar(_edgar_periods(_nvda_ocf_rows(),
                                         ["NetCashProvidedByUsedInOperatingActivities"]))
    assert abs(val - 134.3e9) < 1e8
    assert meta["metodo"].startswith("FY + YTD")
    assert meta["clase"] == "6M"


def test_ttm_cae_a_fy_si_no_hay_ytd():
    C = "Revenues"
    rows = [_row(C, 200e9, "2025-01-27", "2026-01-25", "2026-02-25")]
    val, meta = ttm_edgar(_edgar_periods(rows, ["Revenues"]))
    assert val == 200e9
    assert "solo FY" in meta["metodo"]


def test_ttm_no_mezcla_clases_distintas():
    # un YTD-9m actual sin 9m comparable (solo hay 6m anterior) ⇒ no mezcla ⇒ cae a FY
    C = "NetCashProvidedByUsedInOperatingActivities"
    rows = [
        _row(C, 100e9, "2025-01-27", "2026-01-25", "2026-02-25"),    # FY
        _row(C, 66.5e9, "2026-01-26", "2026-10-26", "2026-11-19"),   # 9M actual
        _row(C, 42.8e9, "2025-01-27", "2025-07-27", "2025-08-26"),   # 6M anterior (clase distinta)
    ]
    val, meta = ttm_edgar(_edgar_periods(rows, [C]))
    assert "solo FY" in meta["metodo"]        # no empareja 9M con 6M


def test_reconstruct_ttm_capex_prefiere_fuente_completa():
    # EDGAR capex implausiblemente bajo vs EODHD ⇒ usa EODHD (más completa) y lo marca
    ocf_rows = _nvda_ocf_rows()
    capexC = "PaymentsToAcquirePropertyPlantAndEquipment"
    capex_rows = [
        _row(capexC, 0.1e9, "2025-01-27", "2026-01-25", "2026-02-25"),
        _row(capexC, 0.1e9, "2025-01-27", "2025-07-27", "2025-08-26"),
        _row(capexC, 0.2e9, "2026-01-26", "2026-07-26", "2026-08-26"),
    ]
    eodhd = {"Financials": {"Cash_Flow": {"quarterly": {
        "2026-07-31": {"totalCashFromOperatingActivities": "24e9", "capitalExpenditures": "2.7e9"},
        "2026-04-30": {"totalCashFromOperatingActivities": "50e9", "capitalExpenditures": "1.8e9"},
        "2026-01-31": {"totalCashFromOperatingActivities": "36e9", "capitalExpenditures": "1.3e9"},
        "2025-10-31": {"totalCashFromOperatingActivities": "24e9", "capitalExpenditures": "1.6e9"},
    }}}}
    res = reconstruct_ttm(ocf_rows + capex_rows, eodhd)
    assert res["ttm"]["capex"]["fuente"] == "EODHD"        # EDGAR subestimaba
    assert any(c[0] == "capex_sec_incompleto" for c in res["controles"])
    assert "fcf" in res["ttm"]


def test_ttm_by_quarters_ventana_comun_suma_trimestres():
    from app.research.ttm import ttm_by_quarters
    def ytd(concept, pairs):
        return {concept: {"units": {"USD": [{"start": s, "end": e, "val": v, "filed": f, "form": fm}
                                             for (s, e, v, f, fm) in pairs]}}}
    rev = [("2025-01-27", "2025-10-26", 147e9, "2025-11-19", "10-Q"),
           ("2025-01-27", "2026-01-25", 215.9e9, "2026-02-25", "10-K"),
           ("2026-01-26", "2026-04-26", 81.6e9, "2026-05-20", "10-Q"),
           ("2026-01-26", "2026-07-26", 177.8e9, "2026-08-26", "10-Q"),
           ("2025-01-27", "2025-07-27", 90e9, "2025-08-26", "10-Q")]
    ocf = [("2025-01-27", "2025-10-26", 66.5e9, "2025-11-19", "10-Q"),
           ("2025-01-27", "2026-01-25", 102.7e9, "2026-02-25", "10-K"),
           ("2026-01-26", "2026-04-26", 50.3e9, "2026-05-20", "10-Q"),
           ("2026-01-26", "2026-07-26", 74.4e9, "2026-08-26", "10-Q"),
           ("2025-01-27", "2025-07-27", 42.8e9, "2025-08-26", "10-Q")]
    usg = {}; usg.update(ytd("RevenueFromContractWithCustomerExcludingAssessedTax", rev))
    usg.update(ytd("NetCashProvidedByUsedInOperatingActivities", ocf))
    r = ttm_by_quarters(usg, {}, {"10-K", "10-Q"})
    assert r["ventana"] == ["2025-10-26", "2026-01-25", "2026-04-26", "2026-07-26"]
    assert abs(r["ttm"]["revenue"]["ttm"] - 303.7e9) < 1e8    # suma de los 4 trimestres de la MISMA ventana
    assert abs(r["ttm"]["ocf"]["ttm"] - 134.3e9) < 1e8
    assert r["ttm"]["revenue"]["fuente"] == "oficial_SEC"
