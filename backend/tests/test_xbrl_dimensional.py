"""E3.2 — pruebas del extractor XBRL dimensional (sintético, sin red)."""
from app.core.xbrl_dimensional import extract_dimensional_facts, latest_annual_by_class

# XBRL inline mínimo: EPS diluido y acciones diluidas por Clase A y Clase B (FY2025), más un
# hecho NO dimensional de otro concepto. Incluye unidades usdPerShare y shares, y escala en acciones.
HTML = """
<html><body>
<ix:header><ix:resources>
  <xbrli:unit id="usdPerShare"><xbrli:divide>
    <xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>
    <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
  </xbrli:divide></xbrli:unit>
  <xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>

  <xbrli:context id="cA"><xbrli:entity><xbrli:segment>
    <xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">vis:ClassACommonStockMember</xbrldi:explicitMember>
    </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-10-01</xbrli:startDate><xbrli:endDate>2025-09-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="cB"><xbrli:entity><xbrli:segment>
    <xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">vis:ClassBCommonStockMember</xbrldi:explicitMember>
    </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-10-01</xbrli:startDate><xbrli:endDate>2025-09-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="cPrev"><xbrli:entity><xbrli:segment>
    <xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">vis:ClassACommonStockMember</xbrldi:explicitMember>
    </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
</ix:resources></ix:header>

<ix:nonFraction name="us-gaap:EarningsPerShareDiluted" contextRef="cA" unitRef="usdPerShare" decimals="2" scale="0">9.95</ix:nonFraction>
<ix:nonFraction name="us-gaap:EarningsPerShareDiluted" contextRef="cB" unitRef="usdPerShare" decimals="2" scale="0">9.90</ix:nonFraction>
<ix:nonFraction name="us-gaap:EarningsPerShareDiluted" contextRef="cPrev" unitRef="usdPerShare" decimals="2" scale="0">8.40</ix:nonFraction>
<ix:nonFraction name="us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding" contextRef="cA" unitRef="shares" decimals="-6" scale="6">1900</ix:nonFraction>
<ix:nonFraction name="us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding" contextRef="cB" unitRef="shares" decimals="-6" scale="6">245</ix:nonFraction>
</body></html>
"""


def test_extrae_por_clase_con_periodo_unidad_y_dimension():
    facts = extract_dimensional_facts(HTML, ["EarningsPerShareDiluted", "WeightedAverageNumberOfDilutedSharesOutstanding"])
    eps = [f for f in facts if f.concept == "EarningsPerShareDiluted"]
    assert len(eps) == 3
    a = [f for f in eps if f.share_class == "ClassACommonStockMember"]
    assert any(abs(f.value - 9.95) < 1e-9 and f.unit == "USD/shares"
               and f.period_end.isoformat() == "2025-09-30" for f in a)


def test_escala_en_acciones_se_aplica():
    facts = extract_dimensional_facts(HTML, ["WeightedAverageNumberOfDilutedSharesOutstanding"])
    a = next(f for f in facts if f.share_class == "ClassACommonStockMember")
    assert abs(a.value - 1_900_000_000) < 1  # 1900 × 10^6
    assert a.unit == "shares"


def test_latest_annual_by_class_no_combina_clases():
    facts = extract_dimensional_facts(HTML, ["EarningsPerShareDiluted"])
    by = latest_annual_by_class(facts, "EarningsPerShareDiluted")
    assert set(by) == {"ClassACommonStockMember", "ClassBCommonStockMember"}
    # Clase A toma el anual MÁS RECIENTE (FY2025 9.95), no el previo (8.40).
    assert abs(by["ClassACommonStockMember"].value - 9.95) < 1e-9
    assert abs(by["ClassBCommonStockMember"].value - 9.90) < 1e-9


def test_ignora_conceptos_no_pedidos():
    facts = extract_dimensional_facts(HTML, ["Revenues"])
    assert facts == []
