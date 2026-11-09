"""Pruebas del enriquecimiento de fundamentales (P0.1) — reglas compartidas prod/eval. Sin red.

Cubre las precisiones del usuario: precedencia del dato oficial, cuarentena de inconsistentes,
equivalencia fiscal (no actualidad ficticia), compatibilidad (períodos/definiciones anual vs TTM),
y datos faltantes (no fabricar FCF TTM ni acciones diluidas)."""
from datetime import date

from app.core.connectors.fundamentals_enrich import (
    enrich_fundamentals, is_materially_fresher, edgar_annual_series, MIN_FISCAL_GAP_DAYS)
from app.core.connectors.registry import ProvenancedField


def _pf(value, period, quality="parcial", currency="USD", as_of=None, name="eodhd_fundamentals"):
    return ProvenancedField(value, quality, name, "EODHD", as_of=as_of, period=period, currency=currency)


# --- equivalencia fiscal (regla >75 días) ---

def test_is_materially_fresher_umbral():
    de = date(2026, 3, 31)
    assert is_materially_fresher(date(2026, 6, 30), de) is True          # +91 días → nuevo trimestre
    assert is_materially_fresher(date(2026, 4, 10), de) is False         # +10 días → jitter, mismo ejercicio
    assert is_materially_fresher(date(2026, 3, 31), de) is False         # mismo período
    assert is_materially_fresher(None, de) is False                      # sin período EODHD
    assert is_materially_fresher(date(2026, 6, 30), None) is True        # EDGAR sin período → aporta
    # frontera exacta: 75 días NO alcanza (debe ser estrictamente mayor)
    assert is_materially_fresher(date(2026, 6, 14), de, min_days=MIN_FISCAL_GAP_DAYS) is False  # 75 días


# --- precedencia: EDGAR vigente no se sobrescribe ---

def test_precedencia_edgar_vigente_no_se_sobrescribe():
    fields = {"revenue": _pf(1000, "2026-06-30", "parcial")}
    out = enrich_fundamentals(fields, edgar_series={}, edgar_data_end=date(2026, 3, 31),
                              same_currency=True, edgar_states={"revenue": "vigente"})
    assert out["revenue"]["usable"] is False            # EDGAR vigente → se preserva el oficial
    assert out["revenue"]["edgar_state"] == "vigente"


def test_aporta_cuando_edgar_falta_y_periodo_es_mas_fresco():
    fields = {"ocf": _pf(500, "2026-06-30", "parcial")}
    out = enrich_fundamentals(fields, edgar_series={}, edgar_data_end=date(2026, 3, 31),
                              same_currency=True, edgar_states={"ocf": "faltante"})
    assert out["ocf"]["usable"] is True                 # llena hueco con interino materialmente fresco
    assert out["ocf"]["state"] == "parcial"
    assert out["ocf"]["period"] == "2026-06-30"


# --- cuarentena: inconsistente se registra, no se usa ---

def test_cuarentena_inconsistente_no_se_usa():
    # EODHD 900 vs EDGAR 1000 en MISMO período/moneda → dif 10% → reconcile marca inconsistente.
    fields = {"revenue_annual": _pf(900, "2025-12-31", "parcial")}
    edgar_series = {"revenue": {"2025-12-31": 1000}}
    out = enrich_fundamentals(fields, edgar_series, edgar_data_end=date(2025, 12, 31),
                              same_currency=True, edgar_states={"revenue": "presente_no_vigente"})
    assert out["revenue_annual"]["state"] == "inconsistente"
    assert out["revenue_annual"]["usable"] is False     # cuarentena: no contamina el payload


def test_reconcile_verificado_confirma_pero_no_aporta_si_edgar_vigente():
    # EODHD coincide con EDGAR (≤2%) → verificado; pero EDGAR ya vigente → no aporta (confirma).
    fields = {"net_income_annual": _pf(1000, "2025-12-31", "parcial")}
    edgar_series = {"net_income": {"2025-12-31": 1000}}
    out = enrich_fundamentals(fields, edgar_series, edgar_data_end=date(2025, 12, 31),
                              same_currency=True, edgar_states={"net_income": "vigente"})
    assert out["net_income_annual"]["state"] == "verificado"
    assert out["net_income_annual"]["usable"] is False


# --- equivalencia fiscal: mismo período no cuenta como mejora ---

def test_mismo_periodo_no_es_mejora_ficticia():
    fields = {"revenue": _pf(1010, "2026-04-05", "parcial")}   # +5 días de EDGAR (jitter)
    out = enrich_fundamentals(fields, edgar_series={}, edgar_data_end=date(2026, 3, 31),
                              same_currency=True, edgar_states={"revenue": "presente_no_vigente"})
    assert out["revenue"]["usable"] is False
    assert out["revenue"]["state"] == "desactualizado"   # presente pero no materialmente más fresco


# --- no fabricar: acciones diluidas EODHD se descartan; FCF sólo si viene ---

def test_no_usa_acciones_diluidas_de_eodhd():
    fields = {"diluted_shares": _pf(400, "2026-06-30", "parcial"),
              "ocf": _pf(500, "2026-06-30", "parcial")}
    out = enrich_fundamentals(fields, edgar_series={}, edgar_data_end=date(2026, 3, 31),
                              same_currency=True, edgar_states={"ocf": "faltante"})
    assert "diluted_shares" not in out                   # sólo EDGAR/oficial, nunca EODHD
    assert "ocf" in out


def test_fcf_faltante_no_se_fabrica():
    # El conector no entregó FCF (None) → faltante; no se inventa a partir de otros campos.
    fields = {"fcf": _pf(None, "2026-06-30", "parcial")}
    out = enrich_fundamentals(fields, edgar_series={}, edgar_data_end=date(2026, 3, 31),
                              same_currency=True, edgar_states={"fcf_ttm": "faltante"})
    assert out["fcf"]["state"] == "faltante"
    assert out["fcf"]["usable"] is False


# --- compatibilidad: anual y TTM conservan período y definición, sin mezclarse ---

def test_compatibilidad_anual_y_ttm_separados():
    fields = {"fcf_annual": _pf(8000, "2025-12-31", "parcial"),
              "fcf": _pf(2100, "2026-06-30", "parcial")}
    out = enrich_fundamentals(fields, edgar_series={}, edgar_data_end=date(2025, 12, 31),
                              same_currency=True, edgar_states={"fcf_annual": "faltante", "fcf_ttm": "faltante"})
    # claves distintas, períodos distintos, sin colisión de definición
    assert out["fcf_annual"]["period"] == "2025-12-31"
    assert out["fcf"]["period"] == "2026-06-30"
    assert out["fcf_annual"]["value"] == 8000 and out["fcf"]["value"] == 2100


def test_moneda_distinta_no_concilia_queda_parcial():
    # Moneda distinta → reconcile no sube a verificado; el interino fresco queda parcial usable.
    fields = {"revenue_annual": _pf(28000, "2025-12-31", "parcial", currency="EUR")}
    edgar_series = {"revenue": {"2025-12-31": 28000}}
    out = enrich_fundamentals(fields, edgar_series, edgar_data_end=date(2024, 12, 31),
                              same_currency=False, edgar_states={"revenue": "faltante"})
    assert out["revenue_annual"]["state"] == "parcial"
    assert out["revenue_annual"]["usable"] is True       # 2025 > 2024 (materialmente más fresco)


# --- P0.3: clasificación de tipo de período y elegibilidad de valoración ---

from app.core.connectors.fundamentals_enrich import classify_period_type, valuation_eligible


def test_classify_trimestre_individual():
    # 4 trimestres suman el anual → trimestres individuales (caso XOM/TSM).
    q = {"2025-03-31": 80, "2025-06-30": 80, "2025-09-30": 80, "2025-12-31": 80}
    y = {"2025-12-31": 320}
    assert classify_period_type(q, y) == "trimestre_individual"


def test_classify_ytd_acumulado():
    # El 'trimestre' de cierre ≈ el anual → YTD acumulado (caso OCF de ASML).
    q = {"2025-03-31": 3, "2025-06-30": 7, "2025-09-30": 10, "2025-12-31": 12.6}
    y = {"2025-12-31": 12.66}
    assert classify_period_type(q, y) == "ytd_acumulado"


def test_classify_indeterminado():
    q = {"2025-09-30": 5}          # ni Σ4T ni cierre coinciden
    y = {"2025-12-31": 40}
    assert classify_period_type(q, y) == "indeterminado"


def test_valuation_eligible_por_tipo():
    assert valuation_eligible("anual") is True
    assert valuation_eligible("ttm") is True
    assert valuation_eligible("balance_instantaneo") is True
    assert valuation_eligible("trimestre_individual") is False   # un trimestre suelto no es base
    assert valuation_eligible("ytd_acumulado") is False
    assert valuation_eligible("indeterminado") is False
    assert valuation_eligible("anual", eps_base_ambigua=True) is False   # EPS ambiguo nunca
