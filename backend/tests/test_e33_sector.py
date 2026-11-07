"""E3.3 — aplicabilidad por sector (no forzar métricas industriales a financieras)."""
from app.core.quality import is_financial_sector, field_applies


def test_sector_financiero_por_sic():
    assert is_financial_sector(6021)   # bancos comerciales
    assert is_financial_sector(6311)   # seguros de vida
    assert is_financial_sector(6211)   # casas de bolsa
    assert not is_financial_sector(7389)   # servicios (V/MA)
    assert not is_financial_sector(2834)   # farma
    assert not is_financial_sector(3571)   # computadoras
    assert not is_financial_sector(None)


def test_margenes_no_aplican_a_financieras():
    for f in ("operating_income", "operating_margin", "gross_profit", "gross_margin"):
        assert field_applies(f, 2834) is True        # industrial: aplica
        assert field_applies(f, 6021) is False        # banco: no aplica


def test_otros_campos_siguen_aplicando_a_financieras():
    for f in ("revenue", "net_income", "eps", "ocf", "net_debt"):
        assert field_applies(f, 6021) is True
    # V/MA (servicios) conservan margen/utilidad operativa
    assert field_applies("operating_margin", 7389) is True
