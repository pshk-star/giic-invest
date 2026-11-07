"""E2 — registro UNIVERSAL de conectores (puro; sin red ni pandas).

Responsabilidades:
  - registrar conectores con su spec declarada (id único);
  - seleccionar, para un `kind` y un contexto (tipo de instrumento, jurisdicción, campo),
    los conectores que cubren, respetando el TOPE DE COSTO (USD 0 por defecto) y `enabled`,
    ordenados por prioridad;
  - fusionar resultados POR CALIDAD, no por recencia ciega: un campo de mayor calidad (p. ej.
    `verificado` oficial) NUNCA es sobrescrito por uno de menor calidad (p. ej. `parcial` de
    fallback); empates se rompen por prioridad del conector;
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

# Escala de calidad por campo (reusa el ladder de core/quality.classify_field). Mayor gana el merge.
# Los veredictos TERMINALES de una fuente con autoridad (bloqueado/no_aplica/indeterminado) son
# AUTORITATIVOS y BLOQUEAN el campo: van por ENCIMA de los valores positivos para que un fallback
# NO los sobrescriba (p. ej. MU bloqueado no lo rellena Yahoo; un trust no_aplica no recibe EPS).
# `faltante` queda al fondo para que, si la fuente oficial simplemente no tiene el dato, un conector
# complementario pueda rellenarlo. Sólo los conectores con autoridad emiten veredictos terminales;
# los de fallback emiten como mucho `parcial`.
QUALITY_RANK = {
    "no_aplica": 6, "bloqueado": 6, "indeterminado": 5,
    "verificado": 4, "derivado": 3, "parcial": 2, "desactualizado": 1, "faltante": 0,
}
# Estados que, al ganar, significan "no usar el valor" (el campo queda marcado, no se rellena).
TERMINAL_QUALITIES = {"no_aplica", "bloqueado", "indeterminado"}


@dataclass
class ProvenancedField:
    """Un valor de campo con su PROCEDENCIA y CALIDAD (trazabilidad por dato)."""
    value: Any
    quality: str                       # clave de QUALITY_RANK
    connector_id: str
    provenance: str
    as_of: Optional[str] = None
    method: Optional[str] = None

    def rank(self) -> int:
        return QUALITY_RANK.get(self.quality, 0)

    def as_dict(self) -> dict:
        return {"value": self.value, "quality": self.quality, "connector_id": self.connector_id,
                "provenance": self.provenance, "as_of": self.as_of, "method": self.method}


@runtime_checkable
class Connector(Protocol):
    spec: ConnectorSpec

    def fetch(self, tickers: List[str], fields: Optional[List[str]] = None,
              context: Optional[Dict[str, dict]] = None) -> Dict[str, Dict[str, ProvenancedField]]:
        """{ticker: {campo: ProvenancedField}}. Best-effort: omite lo que no cubra; no inventa."""
        ...


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

    def connectors_for(self, kind: str, *, instrument_type: Optional[str] = None,
                       jurisdiction: Optional[str] = None, field: Optional[str] = None,
                       include_disabled: bool = False) -> List[Connector]:
        """Conectores que cubren el pedido, dentro del tope de costo, ordenados por prioridad."""
        out = []
        for c in self._connectors.values():
            s = c.spec
            if s.kind != kind:
                continue
            if not include_disabled and not s.enabled:
                continue
            if not self._cost_ok(s):
                continue
            if s.status == ConnectorStatus.DOWN:
                continue
            if not s.coverage.covers(instrument_type=instrument_type, field=field, jurisdiction=jurisdiction):
                continue
            out.append(c)
        out.sort(key=lambda c: c.spec.priority)
        return out

    # --- fusión por calidad ---
    @staticmethod
    def merge_fields(candidates: List[Dict[str, ProvenancedField]],
                     priority_by_id: Dict[str, int]) -> Dict[str, ProvenancedField]:
        """Para cada campo conserva el candidato de MAYOR calidad; empate → menor prioridad (gana
        antes). Un valor de menor calidad NUNCA sobrescribe uno de mayor calidad (ni por recencia)."""
        merged: Dict[str, ProvenancedField] = {}
        for fields_map in candidates:
            for name, pf in (fields_map or {}).items():
                cur = merged.get(name)
                if cur is None:
                    merged[name] = pf
                    continue
                if pf.rank() > cur.rank():
                    merged[name] = pf
                elif pf.rank() == cur.rank():
                    if priority_by_id.get(pf.connector_id, 1e9) < priority_by_id.get(cur.connector_id, 1e9):
                        merged[name] = pf
        return merged

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
        """Consulta los conectores que cubren (por prioridad), con caché por TTL, y fusiona por
        calidad. `context[ticker]` puede llevar instrument_type/jurisdiction para afinar cobertura.
        Devuelve {ticker: {campo: ProvenancedField}}."""
        context = context or {}
        result: Dict[str, Dict[str, ProvenancedField]] = {t: {} for t in tickers}
        # Agrupar por (instrument_type, jurisdiction) para elegir conectores adecuados por lote.
        priority_by_id = {c.spec.id: c.spec.priority for c in self._connectors.values()}
        for t in tickers:
            ctx = context.get(t) or context.get(t.upper()) or {}
            itype = ctx.get("instrument_type")
            juris = ctx.get("jurisdiction")
            conns = self.connectors_for(kind, instrument_type=itype, jurisdiction=juris)
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
            result[t] = self.merge_fields(candidates, priority_by_id)
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
