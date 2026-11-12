"""P2.4 — Pruebas del driver de valoración data-driven (puro, sin red)."""
from __future__ import annotations

from app.research.fundamental_driver import build, DriverResult


def _series(years=6, rev0=10_000e6, growth=0.10, ebit_margin=0.25, shares=1000e6,
            total_debt=2000e6, cash=3000e6, tax_rate=0.15, capex_pct=0.08, dna_pct=0.05, wc_pct=0.01):
    """Serie sintética by_field (periodos ISO ascendentes)."""
    by: dict = {k: {} for k in ("revenue", "operating_income", "shares", "total_debt", "cash",
                                "tax", "net_income", "capex", "dna", "wc_change")}
    rev = rev0
    for i in range(years):
        p = f"{2020 + i}-12-31"
        ebit = rev * ebit_margin
        by["revenue"][p] = rev
        by["operating_income"][p] = ebit
        by["shares"][p] = shares
        by["total_debt"][p] = total_debt
        by["cash"][p] = cash
        by["net_income"][p] = ebit * (1 - tax_rate)
        by["tax"][p] = ebit * tax_rate
        by["capex"][p] = -rev * capex_pct
        by["dna"][p] = rev * dna_pct
        by["wc_change"][p] = rev * wc_pct
        rev *= (1 + growth)
    return by


def test_datos_suficientes_produce_fv_positivo_y_confiable():
    r = build("ACME", "USD", px=50.0, series=_series())
    assert r.status in ("confiable", "experimental")
    assert r.fair_value_usd is not None and r.fair_value_usd > 0
    assert r.margin_pct is not None
    assert r.base is not None and r.assump is not None


def test_sin_ingresos_es_insuficiente_sin_fv():
    s = _series(); s["revenue"] = {}
    r = build("ACME", "USD", px=50.0, series=s)
    assert r.status == "insuficiente"
    assert r.fair_value_usd is None                      # NO inventa FV
    assert any("ingresos" in x for x in r.reasons)


def test_moneda_no_soportada_es_insuficiente():
    r = build("ACME", "JPY", px=50.0, series=_series())
    assert r.status == "insuficiente"
    assert r.fair_value_usd is None


def test_sin_precio_es_insuficiente():
    r = build("ACME", "USD", px=None, series=_series())
    assert r.status == "insuficiente"


def test_margen_implausible_es_insuficiente():
    r = build("ACME", "USD", px=50.0, series=_series(ebit_margin=0.95))  # 95% EBIT: implausible
    assert r.status == "insuficiente"
    assert r.fair_value_usd is None


def test_serie_corta_degrada_a_experimental():
    r = build("ACME", "USD", px=50.0, series=_series(years=2))
    assert r.status == "experimental"
    assert r.confidence in ("baja", "media")
    assert r.fair_value_usd is not None                  # corre, pero con menor confianza


def test_determinista():
    a = build("ACME", "USD", px=50.0, series=_series())
    b = build("ACME", "USD", px=50.0, series=_series())
    assert (a.status, a.fair_value_usd, a.margin_pct) == (b.status, b.fair_value_usd, b.margin_pct)


def test_adr_escala_fv_a_usd():
    # con ADR 5 el FV/acción USD debe ser mayor que con ADR 1 (misma empresa local)
    one = build("X", "USD", px=50.0, series=_series(), adr=1)
    five = build("X", "USD", px=50.0, series=_series(), adr=5)
    assert one.fair_value_usd is not None and five.fair_value_usd is not None
    assert five.fair_value_usd > one.fair_value_usd


# --- Regresión del fix de valoración (diagnóstico PFE): reinversión consistente, sin "crecimiento gratis" ---

def test_reg_empresa_normal_no_bloqueada_y_terminal_defendible():
    # capex > D&A (capital reconstruible): NO bloqueada; crecimiento terminal ≤ 2.5% (no = RF 4.1%)
    r = build("CLEAN", "USD", px=50.0, series=_series(capex_pct=0.08, dna_pct=0.05))
    assert r.inputs.get("acq_amort") is False
    assert not r.inputs.get("review_block")
    assert r.inputs.get("gT") is not None and r.inputs["gT"] <= 0.025 + 1e-9
    assert r.inputs.get("s2c") and r.inputs["s2c"] > 0


def test_reg_bloquea_capital_dominado_por_amortizacion_de_adquisiciones():
    # D&A ≫ capex (patrón PFE/AMGN): capital NO reconstruible del capex ⇒ BLOQUEADO con causa explícita
    r = build("PFELIKE", "USD", px=30.0, series=_series(capex_pct=0.04, dna_pct=0.11))
    assert r.inputs.get("acq_amort") is True
    assert r.inputs.get("review_block") is True
    assert any("amortización de adquisiciones" in x for x in r.inputs.get("review_reasons", []))


def test_reg_sin_crecimiento_gratis_reinversion_positiva_al_crecer():
    # ya NO existe la marca 'free_growth' y la reinversión por s2c es positiva (ROIC implícito > 0)
    r = build("G", "USD", px=50.0, series=_series(growth=0.12, capex_pct=0.07, dna_pct=0.05))
    assert "free_growth" not in r.inputs                 # el mecanismo del bug fue eliminado
    assert r.inputs.get("roic_implied") and r.inputs["roic_implied"] > 0
    assert r.fair_value_usd and r.fair_value_usd > 0


def test_reg_adr_o_divisa_no_usd_queda_en_revision():
    # ADR/divisa no validada en el driver ⇒ bloqueada (en producción gobierna el FV productivo)
    r = build("TSMLIKE", "USD", px=100.0, series=_series(), adr=5)
    assert r.inputs.get("adr_fx_review") is True
    assert r.inputs.get("review_block") is True
