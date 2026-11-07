"""E2 — metadatos DECLARADOS de un conector (puro, sin red ni pandas).

Cada conector declara QUÉ cubre, con QUÉ prioridad, PROCEDENCIA, CALIDAD de origen, cadencia,
limitaciones, estado operativo, nivel de COSTO y política de CACHÉ. El registro (registry.py)
usa SÓLO estos metadatos para decidir a quién consultar y cómo fusionar — de modo que incorporar
un proveedor nuevo (API gratuita, trial o comercial) es declarar su spec + un adaptador fino,
sin tocar la lógica central.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


class CostTier(str, Enum):
    """Nivel de costo. El registro aplica un tope (USD 0 hoy); subir el tope exige autorización."""
    FREE = "free"            # sin costo (SEC EDGAR, Frankfurter, Stooq, Yahoo público)
    TRIAL = "trial"          # cuenta de prueba / cuota gratuita limitada
    COMMERCIAL = "commercial"  # proveedor de pago


COST_ORDER = {CostTier.FREE: 0, CostTier.TRIAL: 1, CostTier.COMMERCIAL: 2}


class ConnectorStatus(str, Enum):
    OPERATIONAL = "operational"
    DEGRADED = "degraded"      # responde parcialmente / con límites
    DOWN = "down"              # no disponible (p. ej. Yahoo stats 401)
    UNKNOWN = "unknown"


class QualityTier(str, Enum):
    """Fiabilidad de ORIGEN declarada (no exactitud auditada del dato puntual)."""
    OFFICIAL = "official"        # fuente primaria del emisor/regulador (SEC EDGAR)
    REGULATORY = "regulatory"    # organismo oficial no-emisor (FX de banco central / BCE)
    AGGREGATOR = "aggregator"    # agregador de mercado (Yahoo, Stooq)
    FALLBACK = "fallback"        # relleno controlado, sólo si no hay mejor
    SAMPLE = "sample"            # datos de ejemplo (nunca producción)


@dataclass(frozen=True)
class Coverage:
    """Qué cubre un conector. Tupla vacía = 'cualquiera' en esa dimensión."""
    instrument_types: Tuple[str, ...] = ()   # p. ej. ("stock","adr"); () = cualquiera
    fields: Tuple[str, ...] = ()              # campos normalizados que puede entregar
    jurisdictions: Tuple[str, ...] = ()       # ISO-2 del emisor; () = cualquiera

    @staticmethod
    def _match(allowed: Tuple[str, ...], value: Optional[str]) -> bool:
        if not allowed:           # cualquiera
            return True
        if value is None:         # sin dato de esa dimensión → no se descarta por ella
            return True
        return value in allowed

    def covers(self, instrument_type: Optional[str] = None, field: Optional[str] = None,
               jurisdiction: Optional[str] = None) -> bool:
        if field is not None and self.fields and field not in self.fields:
            return False
        return (self._match(self.instrument_types, instrument_type)
                and self._match(self.jurisdictions, jurisdiction))


@dataclass(frozen=True)
class ConnectorSpec:
    """Ficha declarada de un conector. Inmutable."""
    id: str                         # identificador único en el registro
    kind: str                       # fundamentals | prices | fx | stats | holdings | identity
    provenance: str                 # etiqueta de atribución (para citar la fuente)
    quality: QualityTier
    priority: int                   # menor = mayor prioridad (se consulta/gana antes)
    cost_tier: CostTier = CostTier.FREE
    coverage: Coverage = field(default_factory=Coverage)
    cache_ttl_s: int = 0            # 0 = sin caché
    rate_limit_per_s: Optional[float] = None
    frequency: Optional[str] = None  # cadencia de actualización de la fuente
    limitations: Tuple[str, ...] = ()
    status: ConnectorStatus = ConnectorStatus.UNKNOWN
    enabled: bool = True

    def as_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "provenance": self.provenance,
            "quality": self.quality.value, "priority": self.priority,
            "cost_tier": self.cost_tier.value,
            "coverage": {
                "instrument_types": list(self.coverage.instrument_types),
                "fields": list(self.coverage.fields),
                "jurisdictions": list(self.coverage.jurisdictions),
            },
            "cache_ttl_s": self.cache_ttl_s, "rate_limit_per_s": self.rate_limit_per_s,
            "frequency": self.frequency, "limitations": list(self.limitations),
            "status": self.status.value, "enabled": self.enabled,
        }
