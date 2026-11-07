"""E2 — registro universal de conectores del Financial Data Engine.

API pública:
  - ConnectorSpec, Coverage, CostTier, QualityTier, ConnectorStatus  (metadatos declarados)
  - Connector (Protocol), ProvenancedField, ConnectorRegistry, QUALITY_RANK, TERMINAL_QUALITIES
  - build_default_registry(...)  (arquitectura $0 con los proveedores existentes)
"""
from .registry import (Connector, ConnectorRegistry, ProvenancedField,  # noqa: F401
                       QUALITY_RANK, TERMINAL_QUALITIES, POSITIVE_RANK, AUTHORITY_RANK,
                       resolve_field)
from .spec import (ConnectorSpec, ConnectorStatus, Coverage, CostTier,  # noqa: F401
                   QualityTier, COST_ORDER)
from .adapters import build_default_registry  # noqa: F401
