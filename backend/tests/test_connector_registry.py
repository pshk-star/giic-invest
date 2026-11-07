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
         status=ConnectorStatus.OPERATIONAL, ttl=0, enabled=True):
    return ConnectorSpec(id=id, kind=kind, provenance=id, quality=QualityTier.OFFICIAL,
                         priority=priority, cost_tier=cost, coverage=coverage or Coverage(),
                         cache_ttl_s=ttl, status=status, enabled=enabled)


def pf(value, quality, cid):
    return ProvenancedField(value, quality, cid, cid)


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


def test_merge_terminal_bloquea_campo_no_lo_pisa_fallback():
    r = ConnectorRegistry()
    r.register(Fake(spec("edgar", priority=10), {"MU": {"eps": pf(None, "bloqueado", "edgar")}}))
    r.register(Fake(spec("yh", priority=60), {"MU": {"eps": pf(7.6, "parcial", "yh")}}))
    merged = r.fetch_merged("fundamentals", ["MU"])
    assert merged["MU"]["eps"].quality == "bloqueado" and merged["MU"]["eps"].value is None


def test_merge_no_aplica_bloquea_eps_de_trust():
    r = ConnectorRegistry()
    r.register(Fake(spec("edgar", priority=10), {"GLD": {"eps": pf(None, "no_aplica", "edgar")}}))
    r.register(Fake(spec("yh", priority=60), {"GLD": {"eps": pf(1.1, "parcial", "yh")}}))
    merged = r.fetch_merged("fundamentals", ["GLD"])
    assert merged["GLD"]["eps"].quality == "no_aplica"


def test_merge_faltante_se_rellena_con_fallback():
    r = ConnectorRegistry()
    r.register(Fake(spec("edgar", priority=10), {"X": {"eps": pf(None, "faltante", "edgar")}}))
    r.register(Fake(spec("yh", priority=60), {"X": {"eps": pf(4.2, "parcial", "yh")}}))
    merged = r.fetch_merged("fundamentals", ["X"])
    assert merged["X"]["eps"].value == 4.2 and merged["X"]["eps"].connector_id == "yh"


def test_merge_empate_calidad_gana_prioridad():
    r = ConnectorRegistry()
    r.register(Fake(spec("a", priority=50), {"X": {"eps": pf(1.0, "parcial", "a")}}))
    r.register(Fake(spec("b", priority=10), {"X": {"eps": pf(2.0, "parcial", "b")}}))
    merged = r.fetch_merged("fundamentals", ["X"])
    assert merged["X"]["eps"].connector_id == "b"


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
