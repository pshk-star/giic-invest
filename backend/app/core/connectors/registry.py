"""E2 — registro UNIVERSAL de conectores (puro; sin red ni pandas).

Responsabilidades:
  - registrar conectores con su spec declarada (id único);
  - seleccionar, para un `kind` y un contexto (tipo de instrumento, jurisdicción, campo), los
    conectores que cubren, respetando el TOPE DE COSTO (USD 0 por defecto) y `enabled`. El tope NO
    sólo se declara: los conectores por encima del tope NI SIQUIERA se invocan;
  - resolver CONFLICTOS entre proveedores por campo, con semántica distinta según el veredicto:
      * no_aplica      → restricción SEMÁNTICA del tipo de instrumento: bloquea el campo (ningún
                         proveedor aporta fundamentales corporativos a un vehículo). Autoritativo.
      * bloqueado      → invalida la observación de ESA fuente, NO el campo: otra fuente
                         independiente con un valor verificable puede resolverlo.
      * indeterminado  → incertidumbre pendiente: otra fuente puede resolverla con un valor
                         positivo, sin asumir que el instrumento es operativo.
    La elección entre valores positivos es MULTICRITERIO (calidad del dato, autoridad de la fuente,
    comparabilidad de moneda/período/ajustes, actualidad) y la prioridad del conector es sólo el
    ÚLTIMO desempate — nunca se elige por prioridad o fecha de forma aislada;
  - cachear por conector con el TTL declarado;
  - exponer un health declarado del catálogo.

Incorporar un proveedor nuevo (gratuito, trial o comercial) = implementar `fetch` + declarar su
spec + `register(...)`. No se toca este archivo ni la lógica consumidora.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from .spec import COST_ORDER, ConnectorSpec, ConnectorStatus, CostTier

# Calidad POSITIVA (hay un valor usable), de mejor a peor.
POSITIVE_RANK = {"verificado": 4, "derivado": 3, "parcial": 2, "desactualizado": 1}
POSITIVE = set(POSITIVE_RANK)
# Veredictos SIN valor usable. Precedencia si no hay ningún positivo que gane.
NON_VALUE_PRECEDENCE = ("bloqueado", "indeterminado", "faltante")
# Estados "no usar el valor" (el campo queda marcado, no se rellena con ese dato).
TERMINAL_QUALITIES = {"no_aplica", "bloqueado", "indeterminado"}
# Autoridad de la FUENTE (derivada de QualityTier) — desempata por fuente, no por prioridad aislada.
AUTHORITY_RANK = {"official": 4, "regulatory": 3, "aggregator": 2, "fallback": 1, "sample": 0}
# Umbral de autoridad para que un veredicto `no_aplica` sea vinculante (restricción semántica sólo
# de fuentes con autoridad; un fallback no puede declarar un instrumento como vehículo).
_NO_APLICA_MIN_AUTHORITY = AUTHORITY_RANK["aggregator"]
# Compat: ranking plano conservado para consumidores antiguos (el merge usa la lógica de abajo).
QUALITY_RANK = {"no_aplica": 7, "bloqueado": 6, "indeterminado": 5,
                "verificado": 4, "derivado": 3, "parcial": 2, "desactualizado": 1, "faltante": 0}


@dataclass
class ProvenancedField:
    """Un valor de campo con su PROCEDENCIA, CALIDAD y atributos de COMPARABILIDAD (trazabilidad por
    dato). period/currency/adjusted permiten elegir el candidato más comparable, no sólo el más
    reciente o el de mayor prioridad."""
    value: Any
    quality: str                       # verificado|derivado|parcial|desactualizado|faltante|
    connector_id: str                  # bloqueado|indeterminado|no_aplica
    provenance: str
    as_of: Optional[str] = None        # fecha de publicación/extracción (actualidad)
    method: Optional[str] = None
    period: Optional[str] = None        # período fiscal del dato (p. ej. '2025-09-27')
    currency: Optional[str] = None      # moneda del dato (ISO-3)
    adjusted: Optional[bool] = None     # ajustado por splits/reexpresión, si aplica

    def is_positive(self) -> bool:
        return self.quality in POSITIVE and self.value is not None

    def rank(self) -> int:
        return QUALITY_RANK.get(self.quality, 0)

    def as_dict(self) -> dict:
        return {"value": self.value, "quality": self.quality, "connector_id": self.connector_id,
                "provenance": self.provenance, "as_of": self.as_of, "method": self.method,
                "period": self.period, "currency": self.currency, "adjusted": self.adjusted}


@runtime_checkable
class Connector(Protocol):
    spec: ConnectorSpec

    def fetch(self, tickers: List[str], fields: Optional[List[str]] = None,
              context: Optional[Dict[str, dict]] = None) -> Dict[str, Dict[str, ProvenancedField]]:
        """{ticker: {campo: ProvenancedField}}. Best-effort: omite lo que no cubra; no inventa."""
        ...


def _as_ordinal(as_of: Optional[str]) -> int:
    """'YYYY-MM-DD' → entero comparable (actualidad). None/ilegible → -1."""
    if not as_of:
        return -1
    try:
        p = str(as_of)[:10].split("-")
        return int(p[0]) * 10000 + int(p[1]) * 100 + int(p[2])
    except (ValueError, IndexError):
        return -1


def _comparability(pf: ProvenancedField, ctx: dict) -> int:
    """Puntúa la comparabilidad del dato con lo esperado (moneda, período, ajustes). Penaliza el
    desajuste de moneda; premia el período esperado y el ajuste por splits cuando se exige."""
    score = 0
    exp_ccy = (ctx or {}).get("expected_currency")
    if exp_ccy and pf.currency:
        score += 2 if pf.currency.upper() == exp_ccy.upper() else -2
    exp_period = (ctx or {}).get("expected_period")
    if exp_period and pf.period:
        score += 1 if str(pf.period) == str(exp_period) else 0
    if (ctx or {}).get("require_adjusted") and pf.adjusted:
        score += 1
    return score


def _selection_key(pf: ProvenancedField, meta_by_id: Dict[str, dict], ctx: dict):
    """Clave lexicográfica MULTICRITERIO. La prioridad del conector es el ÚLTIMO desempate."""
    m = meta_by_id.get(pf.connector_id, {})
    return (
        POSITIVE_RANK.get(pf.quality, 0),                    # 1) calidad del dato
        AUTHORITY_RANK.get(m.get("authority"), 0),           # 2) autoridad de la fuente
        _comparability(pf, ctx),                             # 3) moneda/período/ajustes
        _as_ordinal(pf.as_of),                               # 4) actualidad
        -m.get("priority", 10 ** 9),                         # 5) prioridad (último desempate)
    )


def resolve_field(candidates: List[ProvenancedField], meta_by_id: Dict[str, dict],
                  ctx: Optional[dict] = None) -> Optional[ProvenancedField]:
    """Resuelve el conflicto de un campo entre varios proveedores. Ver la semántica de los tres
    veredictos terminales en el docstring del módulo."""
    ctx = ctx or {}
    if not candidates:
        return None
    # 1) Restricción semántica: no_aplica de una fuente con autoridad bloquea el campo.
    naps = [c for c in candidates if c.quality == "no_aplica"
            and AUTHORITY_RANK.get(meta_by_id.get(c.connector_id, {}).get("authority"), 0) >= _NO_APLICA_MIN_AUTHORITY]
    if naps:
        return max(naps, key=lambda c: _selection_key(c, meta_by_id, ctx))
    # 2) Cualquier valor POSITIVO de una fuente independiente gana (bloqueado/indeterminado NO lo
    #    vetan: invalidan sólo la observación de su propia fuente).
    positives = [c for c in candidates if c.is_positive()]
    if positives:
        return max(positives, key=lambda c: _selection_key(c, meta_by_id, ctx))
    # 3) Sin valor positivo: conserva el veredicto más fuerte (no usar el dato), por precedencia.
    for q in NON_VALUE_PRECEDENCE:
        same = [c for c in candidates if c.quality == q]
        if same:
            return max(same, key=lambda c: _selection_key(c, meta_by_id, ctx))
    return candidates[0]


class ConnectorRegistry:
    def __init__(self, max_cost: CostTier = CostTier.FREE, clock: Callable[[], float] = time.monotonic):
        self._connectors: Dict[str, Connector] = {}
        self.max_cost = max_cost
        self._clock = clock
        self._cache: Dict[str, tuple] = {}   # key -> (expira_en, {campo: ProvenancedField})

    # --- registro ---
    def register(self, connector: Connector) -> None:
        spec = connector.spec
        if spec.id in self._connectors:
            raise ValueError(f"conector duplicado: {spec.id!r}")
        self._connectors[spec.id] = connector

    def unregister(self, connector_id: str) -> None:
        self._connectors.pop(connector_id, None)

    def ids(self) -> List[str]:
        return list(self._connectors)

    def _cost_ok(self, spec: ConnectorSpec) -> bool:
        return COST_ORDER[spec.cost_tier] <= COST_ORDER[self.max_cost]

    def _meta_by_id(self) -> Dict[str, dict]:
        return {c.spec.id: {"authority": c.spec.quality.value, "priority": c.spec.priority}
                for c in self._connectors.values()}

    def connectors_for(self, kind: str, *, instrument_type: Optional[str] = None,
                       jurisdiction: Optional[str] = None, field: Optional[str] = None,
                       include_disabled: bool = False) -> List[Connector]:
        """Conectores que cubren el pedido, DENTRO del tope de costo (los de arriba ni se devuelven
        ni se invocan), ordenados por prioridad (orden de consulta; la elección final es multicrit.)."""
        out = []
        for c in self._connectors.values():
            s = c.spec
            if s.kind != kind:
                continue
            if not include_disabled and not s.enabled:
                continue
            if not self._cost_ok(s):           # GATE DE COSTO: excluye de la selección Y de la invocación
                continue
            if s.status == ConnectorStatus.DOWN:
                continue
            if not s.coverage.covers(instrument_type=instrument_type, field=field, jurisdiction=jurisdiction):
                continue
            out.append(c)
        out.sort(key=lambda c: c.spec.priority)
        return out

    # --- fusión por conflicto (semántica de 3 veredictos + selección multicriterio) ---
    def merge_fields(self, per_connector: List[Dict[str, ProvenancedField]],
                     meta_by_id: Optional[Dict[str, dict]] = None,
                     ctx: Optional[dict] = None) -> Dict[str, ProvenancedField]:
        meta_by_id = meta_by_id if meta_by_id is not None else self._meta_by_id()
        by_field: Dict[str, List[ProvenancedField]] = {}
        for fields_map in per_connector:
            for name, pf in (fields_map or {}).items():
                by_field.setdefault(name, []).append(pf)
        return {name: resolve_field(cands, meta_by_id, ctx) for name, cands in by_field.items()}

    def _cache_get(self, key: str):
        hit = self._cache.get(key)
        if not hit:
            return None
        expires, payload = hit
        if expires is not None and self._clock() >= expires:
            self._cache.pop(key, None)
            return None
        return payload

    def _cache_put(self, key: str, ttl_s: int, payload):
        if ttl_s and ttl_s > 0:
            self._cache[key] = (self._clock() + ttl_s, payload)

    def fetch_merged(self, kind: str, tickers: List[str], *, fields: Optional[List[str]] = None,
                     context: Optional[Dict[str, dict]] = None
                     ) -> Dict[str, Dict[str, ProvenancedField]]:
        """Consulta los conectores que cubren (dentro del tope de costo), con caché por TTL, y
        resuelve conflictos por campo. `context[ticker]` puede llevar instrument_type/jurisdiction
        (afinan cobertura) y expected_currency/expected_period/require_adjusted (afinan la elección).
        Devuelve {ticker: {campo: ProvenancedField}}."""
        context = context or {}
        result: Dict[str, Dict[str, ProvenancedField]] = {t: {} for t in tickers}
        meta_by_id = self._meta_by_id()
        for t in tickers:
            ctx = context.get(t) or context.get(t.upper()) or {}
            conns = self.connectors_for(kind, instrument_type=ctx.get("instrument_type"),
                                        jurisdiction=ctx.get("jurisdiction"))
            candidates: List[Dict[str, ProvenancedField]] = []
            for c in conns:
                ckey = f"{c.spec.id}|{t}|{','.join(fields or [])}"
                cached = self._cache_get(ckey)
                if cached is not None:
                    candidates.append(cached)
                    continue
                try:
                    got = c.fetch([t], fields=fields, context={t: ctx})
                except Exception:
                    got = {}
                fields_map = (got or {}).get(t, {}) or {}
                self._cache_put(ckey, c.spec.cache_ttl_s, fields_map)
                candidates.append(fields_map)
            result[t] = self.merge_fields(candidates, meta_by_id, ctx)
        return result

    # --- salud declarada ---
    def catalog(self) -> List[dict]:
        return [c.spec.as_dict() for c in sorted(self._connectors.values(), key=lambda c: (c.spec.kind, c.spec.priority))]

    def health(self) -> dict:
        by_kind: Dict[str, int] = {}
        by_cost: Dict[str, int] = {}
        for c in self._connectors.values():
            by_kind[c.spec.kind] = by_kind.get(c.spec.kind, 0) + 1
            by_cost[c.spec.cost_tier.value] = by_cost.get(c.spec.cost_tier.value, 0) + 1
        return {"n_conectores": len(self._connectors), "tope_costo": self.max_cost.value,
                "por_tipo": by_kind, "por_costo": by_cost, "catalogo": self.catalog()}
