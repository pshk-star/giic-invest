"""E2 — pruebas del registro universal de conectores (sin red; conectores falsos)."""
import pytest

from app.core.connectors import (ConnectorRegistry, ConnectorSpec, Coverage, CostTier,
                                  ProvenancedField, QualityTier, build_default_registry)
from app.core.connectors.spec import ConnectorStatus


class Fake:
    """Conector falso: devuelve un mapa fijo de campos y cuenta las llamadas (para probar caché)."""
    def __init__(self, spec, payload):
        self.spec = spec
        self.payload = payload          # {ticker: {campo: ProvenancedField}}
        self.calls = 0

    def fetch(self, tickers, fields=None, context=None):
        self.calls += 1
        return {t: self.payload.get(t, {}) for t in tickers}


def spec(id, kind="fundamentals", priority=10, cost=CostTier.FREE, coverage=None,
         status=ConnectorStatus.OPERATIONAL, ttl=0, enabled=True, quality=QualityTier.OFFICIAL):
    return ConnectorSpec(id=id, kind=kind, provenance=id, quality=quality,
                         priority=priority, cost_tier=cost, coverage=coverage or Coverage(),
                         cache_ttl_s=ttl, status=status, enabled=enabled)


def pf(value, quality, cid, **kw):
    return ProvenancedField(value, quality, cid, cid, **kw)


# --- registro ---
def test_register_y_duplicado():
    r = ConnectorRegistry()
    r.register(Fake(spec("a"), {}))
    with pytest.raises(ValueError):
        r.register(Fake(spec("a"), {}))
    assert r.ids() == ["a"]


# --- selección por cobertura + costo + estado ---
def test_cost_gate_excluye_comercial_por_defecto():
    r = ConnectorRegistry()  # max_cost=FREE
    r.register(Fake(spec("free1", cost=CostTier.FREE), {}))
    r.register(Fake(spec("paid", cost=CostTier.COMMERCIAL), {}))
    ids = [c.spec.id for c in r.connectors_for("fundamentals")]
    assert ids == ["free1"]


def test_cost_gate_habilita_comercial_con_tope():
    r = ConnectorRegistry(max_cost=CostTier.COMMERCIAL)
    r.register(Fake(spec("free1", priority=10, cost=CostTier.FREE), {}))
    r.register(Fake(spec("paid", priority=5, cost=CostTier.COMMERCIAL), {}))
    ids = [c.spec.id for c in r.connectors_for("fundamentals")]
    assert ids == ["paid", "free1"]          # ordenado por prioridad


def test_down_y_disabled_se_excluyen():
    r = ConnectorRegistry()
    r.register(Fake(spec("down", status=ConnectorStatus.DOWN), {}))
    r.register(Fake(spec("off", enabled=False), {}))
    r.register(Fake(spec("ok"), {}))
    assert [c.spec.id for c in r.connectors_for("fundamentals")] == ["ok"]


def test_cobertura_por_tipo_y_campo_y_jurisdiccion():
    r = ConnectorRegistry()
    r.register(Fake(spec("etf_only", coverage=Coverage(instrument_types=("etf",))), {}))
    r.register(Fake(spec("eps_only", coverage=Coverage(fields=("eps",))), {}))
    r.register(Fake(spec("us_only", coverage=Coverage(jurisdictions=("US",))), {}))
    assert [c.spec.id for c in r.connectors_for("fundamentals", instrument_type="stock")] == ["eps_only", "us_only"]
    assert "eps_only" in [c.spec.id for c in r.connectors_for("fundamentals", field="eps")]
    assert "eps_only" not in [c.spec.id for c in r.connectors_for("fundamentals", field="net_debt")]
    assert [c.spec.id for c in r.connectors_for("fundamentals", jurisdiction="TW")] == ["etf_only", "eps_only"]


# --- merge por calidad ---
def test_merge_oficial_verificado_gana_a_fallback_parcial():
    r = ConnectorRegistry()
    r.register(Fake(spec("edgar", priority=10), {"X": {"eps": pf(5.0, "verificado", "edgar")}}))
    r.register(Fake(spec("yh", priority=60), {"X": {"eps": pf(4.2, "parcial", "yh")}}))
    merged = r.fetch_merged("fundamentals", ["X"])
    assert merged["X"]["eps"].value == 5.0 and merged["X"]["eps"].connector_id == "edgar"


def test_no_aplica_restriccion_semantica_bloquea_aunque_haya_valor():
    # no_aplica (de fuente con autoridad) es restricción del TIPO de instrumento: ni un verificado
    # independiente debe poblar un fundamental corporativo de un vehículo.
    r = ConnectorRegistry()
    r.register(Fake(spec("edgar", priority=10), {"GLD": {"eps": pf(None, "no_aplica", "edgar")}}))
    r.register(Fake(spec("vendor", priority=5), {"GLD": {"eps": pf(1.1, "verificado", "vendor")}}))
    merged = r.fetch_merged("fundamentals", ["GLD"])
    assert merged["GLD"]["eps"].quality == "no_aplica" and merged["GLD"]["eps"].value is None


def test_no_aplica_de_fallback_no_es_vinculante():
    # Un fallback NO tiene autoridad para declarar un instrumento como vehículo: su no_aplica no
    # bloquea, y un valor positivo independiente resuelve.
    from app.core.connectors.spec import QualityTier
    s_fb = ConnectorSpec(id="fb", kind="fundamentals", provenance="fb", quality=QualityTier.FALLBACK,
                         priority=5)
    r = ConnectorRegistry()
    r.register(Fake(s_fb, {"X": {"eps": pf(None, "no_aplica", "fb")}}))
    r.register(Fake(spec("edgar", priority=10), {"X": {"eps": pf(3.0, "verificado", "edgar")}}))
    merged = r.fetch_merged("fundamentals", ["X"])
    assert merged["X"]["eps"].value == 3.0


def test_bloqueado_lo_resuelve_proveedor_independiente():
    # bloqueado invalida la observación de ESA fuente, no el campo: otro proveedor independiente
    # con un valor positivo lo resuelve.
    r = ConnectorRegistry()
    r.register(Fake(spec("edgar", priority=10), {"MU": {"eps": pf(None, "bloqueado", "edgar")}}))
    r.register(Fake(spec("vendor", priority=50), {"MU": {"eps": pf(7.6, "verificado", "vendor")}}))
    merged = r.fetch_merged("fundamentals", ["MU"])
    assert merged["MU"]["eps"].value == 7.6 and merged["MU"]["eps"].connector_id == "vendor"


def test_bloqueado_sin_alternativa_queda_bloqueado():
    # Si nadie aporta un valor positivo, el campo queda bloqueado (no se usa el dato).
    r = ConnectorRegistry()
    r.register(Fake(spec("edgar", priority=10), {"MU": {"eps": pf(None, "bloqueado", "edgar")}}))
    merged = r.fetch_merged("fundamentals", ["MU"])
    assert merged["MU"]["eps"].quality == "bloqueado"


def test_indeterminado_lo_resuelve_otra_fuente_sin_asumir_operativo():
    r = ConnectorRegistry()
    r.register(Fake(spec("edgar", priority=10), {"X": {"eps": pf(None, "indeterminado", "edgar")}}))
    r.register(Fake(spec("vendor", priority=50), {"X": {"eps": pf(2.5, "verificado", "vendor")}}))
    merged = r.fetch_merged("fundamentals", ["X"])
    assert merged["X"]["eps"].value == 2.5


def test_indeterminado_sin_alternativa_sigue_indeterminado():
    # Sin otra fuente, NO se asume operativo: queda indeterminado.
    r = ConnectorRegistry()
    r.register(Fake(spec("edgar", priority=10), {"X": {"eps": pf(None, "indeterminado", "edgar")}}))
    merged = r.fetch_merged("fundamentals", ["X"])
    assert merged["X"]["eps"].quality == "indeterminado"


def test_merge_faltante_se_rellena_con_fallback():
    r = ConnectorRegistry()
    r.register(Fake(spec("edgar", priority=10), {"X": {"eps": pf(None, "faltante", "edgar")}}))
    r.register(Fake(spec("yh", priority=60), {"X": {"eps": pf(4.2, "parcial", "yh")}}))
    merged = r.fetch_merged("fundamentals", ["X"])
    assert merged["X"]["eps"].value == 4.2 and merged["X"]["eps"].connector_id == "yh"


def test_merge_empate_total_gana_prioridad_como_ultimo_desempate():
    # Mismos calidad/autoridad/comparabilidad/actualidad → la prioridad decide (último criterio).
    r = ConnectorRegistry()
    r.register(Fake(spec("a", priority=50), {"X": {"eps": pf(1.0, "parcial", "a")}}))
    r.register(Fake(spec("b", priority=10), {"X": {"eps": pf(2.0, "parcial", "b")}}))
    merged = r.fetch_merged("fundamentals", ["X"])
    assert merged["X"]["eps"].connector_id == "b"


# --- selección MULTICRITERIO (no prioridad/fecha aislada) ---
def test_calidad_vence_a_prioridad():
    # Un verificado de baja prioridad gana a un parcial de alta prioridad (calidad > prioridad).
    r = ConnectorRegistry()
    r.register(Fake(spec("hi", priority=1), {"X": {"eps": pf(1.0, "parcial", "hi")}}))
    r.register(Fake(spec("lo", priority=99), {"X": {"eps": pf(2.0, "verificado", "lo")}}))
    assert r.fetch_merged("fundamentals", ["X"])["X"]["eps"].connector_id == "lo"


def test_autoridad_de_fuente_vence_a_prioridad():
    # Igual calidad: la fuente con más autoridad (official) gana al aggregator aunque tenga peor prio.
    r = ConnectorRegistry()
    r.register(Fake(spec("agg", priority=1, quality=QualityTier.AGGREGATOR),
                    {"X": {"eps": pf(1.0, "parcial", "agg")}}))
    r.register(Fake(spec("off", priority=99, quality=QualityTier.OFFICIAL),
                    {"X": {"eps": pf(2.0, "parcial", "off")}}))
    assert r.fetch_merged("fundamentals", ["X"])["X"]["eps"].connector_id == "off"


def test_comparabilidad_moneda_vence_a_prioridad_y_actualidad():
    # Dos verificados: uno en EUR más reciente y de mejor prioridad; otro en USD (moneda esperada).
    # La comparabilidad de moneda pesa más que actualidad y prioridad.
    r = ConnectorRegistry()
    r.register(Fake(spec("eur", priority=1), {"X": {"eps": pf(9.0, "verificado", "eur",
                                                              currency="EUR", as_of="2026-09-30")}}))
    r.register(Fake(spec("usd", priority=99), {"X": {"eps": pf(8.0, "verificado", "usd",
                                                              currency="USD", as_of="2025-12-31")}}))
    merged = r.fetch_merged("fundamentals", ["X"], context={"X": {"expected_currency": "USD"}})
    assert merged["X"]["eps"].connector_id == "usd"


def test_actualidad_desempata_antes_que_prioridad():
    # Igual calidad/autoridad/comparabilidad: gana el más reciente (actualidad > prioridad).
    r = ConnectorRegistry()
    r.register(Fake(spec("old", priority=1), {"X": {"eps": pf(1.0, "verificado", "old", as_of="2024-12-31")}}))
    r.register(Fake(spec("new", priority=99), {"X": {"eps": pf(2.0, "verificado", "new", as_of="2026-09-30")}}))
    assert r.fetch_merged("fundamentals", ["X"])["X"]["eps"].connector_id == "new"


# --- gate de costo: IMPIDE la invocación, no sólo la declara ---
def test_cost_gate_no_invoca_fetch_de_comercial():
    r = ConnectorRegistry(max_cost=CostTier.FREE)
    r.register(Fake(spec("edgar", priority=10), {"X": {"eps": pf(1.0, "parcial", "edgar")}}))
    paid = Fake(spec("vendor", priority=5, cost=CostTier.COMMERCIAL),
                {"X": {"eps": pf(9.0, "verificado", "vendor")}})
    r.register(paid)
    r.fetch_merged("fundamentals", ["X"])
    assert paid.calls == 0            # NUNCA se invocó el conector de pago
    r.max_cost = CostTier.COMMERCIAL  # autorización
    r.fetch_merged("fundamentals", ["X"])
    assert paid.calls == 1            # ahora sí se invoca


# --- contexto por ticker afina cobertura ---
def test_context_rutea_por_instrument_type():
    r = ConnectorRegistry()
    r.register(Fake(spec("equity_only", coverage=Coverage(instrument_types=("stock",))),
                    {"GLD": {"eps": pf(9.9, "parcial", "equity_only")}}))
    merged = r.fetch_merged("fundamentals", ["GLD"], context={"GLD": {"instrument_type": "etf"}})
    assert merged["GLD"] == {}   # el conector de equity no cubre un etf → nada


# --- caché TTL ---
def test_cache_ttl_evita_reconsulta():
    clock = {"t": 0.0}
    r = ConnectorRegistry(clock=lambda: clock["t"])
    f = Fake(spec("edgar", ttl=100), {"X": {"eps": pf(5.0, "verificado", "edgar")}})
    r.register(f)
    r.fetch_merged("fundamentals", ["X"])
    r.fetch_merged("fundamentals", ["X"])          # dentro del TTL → sin reconsulta
    assert f.calls == 1
    clock["t"] = 150.0                              # expira
    r.fetch_merged("fundamentals", ["X"])
    assert f.calls == 2


# --- extensibilidad: añadir un proveedor = sólo registrar ---
def test_agregar_proveedor_comercial_solo_requiere_registrar():
    r = ConnectorRegistry(max_cost=CostTier.FREE)
    r.register(Fake(spec("edgar", priority=10), {"X": {"eps": pf(None, "faltante", "edgar")}}))
    paid = Fake(spec("vendor_x", priority=5, cost=CostTier.COMMERCIAL),
                {"X": {"eps": pf(5.0, "verificado", "vendor_x")}})
    r.register(paid)
    # Con tope FREE el comercial no participa → el campo sigue faltante.
    assert r.fetch_merged("fundamentals", ["X"])["X"]["eps"].quality == "faltante"
    # Subir el tope (autorización) lo habilita SIN cambiar el conector ni el núcleo.
    r.max_cost = CostTier.COMMERCIAL
    merged = r.fetch_merged("fundamentals", ["X"])
    assert merged["X"]["eps"].value == 5.0 and merged["X"]["eps"].connector_id == "vendor_x"


# --- registro por defecto (offline) ---
def test_default_registry_catalogo_offline():
    reg = build_default_registry(edgar_user_agent=None)
    cat = reg.catalog()
    ids = {c["id"] for c in cat}
    assert {"edgar_companyfacts", "yahoo_stats", "frankfurter_fx", "prices_yahoo_stooq"} <= ids
    h = reg.health()
    assert h["tope_costo"] == "free" and h["n_conectores"] == 4
    # EDGAR declarado oficial y operativo; Yahoo stats declarado DOWN (401) con honestidad.
    edgar = next(c for c in cat if c["id"] == "edgar_companyfacts")
    yh = next(c for c in cat if c["id"] == "yahoo_stats")
    assert edgar["quality"] == "official" and edgar["status"] == "operational"
    assert yh["status"] == "down"
