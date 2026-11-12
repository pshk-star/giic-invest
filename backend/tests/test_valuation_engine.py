"""Pruebas del motor de valoración v2 (puras, sin red): reconciliación, FCFF DCF, controles, validación."""
from __future__ import annotations

from app.research.valuation_engine import (reconcile, normalize, value_from_norm, evaluate,
                                           RF, ERP, FX_TO_USD, YEARS)


def _series(years=6, rev0=100_000e6, growth=0.08, op_margin=0.30, shares=1000e6,
            equity=60_000e6, debt=30_000e6, cash=20_000e6, tax=0.15, ocf_margin=0.28, capex_margin=0.06,
            ccy="USD"):
    by = {k: {} for k in ("revenue", "operating_income", "net_income", "tax", "ocf", "capex",
                          "cash", "total_debt", "equity", "shares")}
    rev = rev0
    for i in range(years):
        p = f"{2020+i}-12-31"
        ebit = rev * op_margin
        by["revenue"][p] = rev
        by["operating_income"][p] = ebit
        by["net_income"][p] = ebit * (1 - tax)
        by["tax"][p] = ebit * tax
        by["ocf"][p] = rev * ocf_margin
        by["capex"][p] = -rev * capex_margin
        by["cash"][p] = cash
        by["total_debt"][p] = debt
        by["equity"][p] = equity
        by["shares"][p] = shares
        rev *= (1 + growth)
    return {"currency": ccy, "by_field": by}


def test_reconcile_prefiere_fuente_mas_completa_y_marca_discrepancia():
    edgar = {"currency": "USD", "by_field": {"revenue": {"2023-12-31": 100.0, "2022-12-31": 90.0}}}
    eodhd = {"currency": "USD", "by_field": {"revenue": {"2023-12-31": 115.0}}}  # 1 periodo, difiere 15%
    rec = reconcile(edgar, eodhd)
    assert rec.provenance["revenue"] == "EDGAR"         # más completa
    assert rec.discrepancies["revenue"] > 0.10          # discrepancia registrada
    assert any("discrepancia" in x for x in rec.notes)


def test_empresa_sana_valida_y_fv_positivo_reproducible():
    out = evaluate("TESTCO", _series(), {"currency": "USD", "by_field": {}}, price_local=50.0)
    assert out.result is not None
    r = out.result
    assert r.fair_value_usd and r.fair_value_usd > 0
    assert r.wacc > r.gT                                 # WACC > crecimiento terminal
    assert 0 < r.terminal_weight < 1
    assert r.status in ("consistente", "en_revision")
    # reproducibilidad: Ke = RF + beta·ERP
    assert abs(r.ke - (RF["USD"] + r.inputs["beta"] * ERP["USD"])) < 1e-9


def test_control_reinversion_mayor_que_roic_falla_duro():
    # crecimiento altísimo con margen/capital que da ROIC bajo ⇒ g1 >= ROIC ⇒ no_valorable
    s = _series(growth=0.30, op_margin=0.05, equity=200_000e6, debt=100_000e6, cash=0)
    out = evaluate("BADCO", s, {"currency": "USD", "by_field": {}}, price_local=50.0)
    # o falla duro por reinversión>ROIC, o queda no_valorable; nunca 'validado'
    assert out.status in ("no_valorable", "en_revision")
    if out.result:
        assert out.result.status != "consistente"


def test_capital_no_reconstruible_no_valorable():
    s = _series()
    for f in ("equity", "total_debt", "cash"):
        s["by_field"][f] = {}
    out = evaluate("NOCAP", s, {"currency": "USD", "by_field": {}}, price_local=50.0)
    assert out.status == "no_valorable"
    assert out.result is None


def test_acciones_implausibles_no_valorable():
    s = _series(shares=500)                              # 500 acciones ⇒ error de escala
    out = evaluate("SCALE", s, {"currency": "USD", "by_field": {}}, price_local=50.0)
    assert out.status == "no_valorable"


def test_margen_extremo_queda_en_revision_no_calibra():
    # precio muy bajo respecto al FV ⇒ margen de seguridad extremo ⇒ en_revision (no se ajusta el FV)
    s = _series(op_margin=0.45, growth=0.12)
    out = evaluate("EXTREME", s, {"currency": "USD", "by_field": {}}, price_local=1.0)
    assert out.result is not None
    # el FV no se toca; el margen extremo degrada a revisión
    if abs(out.result.margin_of_safety or 0) > 0.60:
        assert out.result.status == "en_revision"


def test_adr_escala_a_usd_con_fx():
    # TWD con ADR 5: FV USD = FV_local × 5 × FX(TWD→USD)
    s = _series(ccy="TWD")
    out = evaluate("TSMX", s, {"currency": "TWD", "by_field": {}}, price_local=600.0, adr=5)
    assert out.result is not None
    r = out.result
    assert r.fair_value_local is not None and r.fair_value_usd is not None
    assert abs(r.fair_value_usd - r.fair_value_local * 5 * FX_TO_USD["TWD"]) < 0.1


def test_fuentes_inconsistentes_mandan_a_revision():
    # ingresos que difieren fuerte entre EDGAR y EODHD (error de datos/escala) ⇒ en_revision, no validado
    edgar = _series()
    eodhd = _series()
    # EODHD con más periodos para que gane en 'revenue', y con escala 2x (discrepancia > 25%)
    for p in list(eodhd["by_field"]["revenue"]):
        eodhd["by_field"]["revenue"][p] = eodhd["by_field"]["revenue"][p] * 2
    eodhd["by_field"]["revenue"]["2019-12-31"] = 80_000e6   # periodo extra: EODHD más completa
    out = evaluate("NFLXLIKE", edgar, eodhd, price_local=50.0)
    assert out.result is not None
    assert "fuentes_consistentes" in [c[0] for c in out.result.controls if not c[1]]
    assert out.result.status == "en_revision"


def test_determinista():
    a = evaluate("D", _series(), {"currency": "USD", "by_field": {}}, 50.0).result
    b = evaluate("D", _series(), {"currency": "USD", "by_field": {}}, 50.0).result
    assert (a.fair_value_usd, a.wacc, a.status) == (b.fair_value_usd, b.wacc, b.status)
