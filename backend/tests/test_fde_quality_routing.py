"""E1 — pruebas del motor de calidad extraído y del routing por tipo de instrumento.

Fijan como regresión: (1) el guard de plausibilidad conserva umbrales y la razón de MU es
NEUTRAL (no atribuye la anomalía al emisor), (2) el routing por SIC cortocircuita fondos/trusts
sin métricas corporativas y NO toca empresas operativas (incluidas financieras/pagos).
"""
from app.core.quality import assess_plausibility, is_non_operating, classify_field, FUND_TRUST_SIC
from app.providers.edgar import parse_companyfacts


# --- guard de plausibilidad (umbrales idénticos al original) ---
def test_ni_mayor_que_ingresos_bloquea():
    q, reason = assess_plausibility(ni_l=100.0, rev_l=50.0, eg_raw=None, rg_raw=None)
    assert q == "bloqueado" and "magnitud imposible" in reason


def test_salto_eps_extremo_bloquea_y_razon_es_neutral():
    # Caso tipo MU: salto de EPS > 300% con multiplicador de ingresos distinto.
    q, reason = assess_plausibility(ni_l=None, rev_l=None, eg_raw=8.79, rg_raw=2.56)
    assert q == "bloqueado"
    # E1 cond. 5: NO imputar al emisor ni al 10-K; sólo describir y bloquear hasta contraste oficial.
    assert "documentos financieros oficiales" in reason
    assert "probable error de origen" not in reason
    assert "verificar 10-K original" not in reason


def test_margen_neto_alto_sospechoso():
    q, reason = assess_plausibility(ni_l=70.0, rev_l=100.0, eg_raw=None, rg_raw=None)
    assert q == "sospechoso" and "margen neto" in reason


def test_salto_eps_moderado_sospechoso():
    q, _ = assess_plausibility(ni_l=None, rev_l=None, eg_raw=2.0, rg_raw=None)
    assert q == "sospechoso"


def test_valores_normales_ok():
    q, reason = assess_plausibility(ni_l=20.0, rev_l=100.0, eg_raw=0.12, rg_raw=0.1)
    assert q == "ok" and reason is None


# --- routing por SIC (señal universal, no por ticker) ---
def test_sic_de_trust_es_no_operativo():
    for sic in FUND_TRUST_SIC:
        assert is_non_operating(sic) is True


def test_sic_de_empresa_operativa_no_es_no_operativo():
    assert is_non_operating(2834) is False      # pharma
    assert is_non_operating(3571) is False       # computers
    assert is_non_operating(7389) is False       # services-computer (V/MA)
    assert is_non_operating(6021) is False        # national commercial banks


def test_descripcion_como_senal_secundaria():
    # Código desconocido pero descripción de vehículo → no operativo…
    assert is_non_operating(None, "Commodity Trust - Gold") is True
    # …salvo que la descripción sea de un operativo (banco), que prevalece.
    assert is_non_operating(None, "State Commercial Banks") is False
    assert is_non_operating(None, None) is False


def test_parse_companyfacts_cortocircuita_fondo():
    # Un trust (SIC de vehículo) NO recibe métricas corporativas, aunque tuviera 'facts'.
    f = parse_companyfacts({"facts": {}}, "GLD", price=180.0, sic=6221,
                           sic_desc="Commodity Contracts Brokers & Dealers")
    assert f.data_quality == "no_aplica"
    assert f.instrument_class == "etf_o_trust"
    assert f.eps is None and f.roe is None and f.net_debt is None and f.pe_ttm is None
    assert "no tienen significado económico" in f.quality_reason


def test_parse_companyfacts_empresa_operativa_sin_sic_igual_que_antes():
    # Sin SIC, el comportamiento es el de empresa operativa (no cortocircuita).
    f = parse_companyfacts({"facts": {}}, "XX", price=None)
    assert f.data_quality == "ok"
    assert f.instrument_class == "empresa_operativa"


# --- clasificación por campo ---
def test_classify_field_estados():
    assert classify_field(None) == "faltante"
    assert classify_field(1.0, independent=True) == "verificado"
    assert classify_field(1.0, derived=True) == "derivado"
    assert classify_field(1.0) == "parcial"
    assert classify_field(1.0, blocked=True) == "bloqueado"
    assert classify_field(1.0, not_applicable=True) == "no_aplica"
