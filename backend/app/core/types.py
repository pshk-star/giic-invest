"""Tipos de dominio (dataclasses puras, sin ORM ni pydantic).

Son las estructuras con las que trabaja el núcleo. La capa web las traduce
a/desde esquemas pydantic y la capa de datos a/desde modelos ORM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class AssetClass(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    CASH = "cash"


@dataclass(frozen=True)
class Instrument:
    """Un instrumento negociable identificado de forma única por ticker+exchange."""
    ticker: str
    name: str
    asset_class: AssetClass
    exchange: str          # MIC o código del proveedor, p.ej. "US", "XTAI", "BMV"
    country: str           # ISO-2, p.ej. "US", "TW", "MX"
    sector: Optional[str] = None
    currency: str = "USD"


@dataclass
class Position:
    """Una posición abierta en la cartera."""
    instrument: Instrument
    quantity: float
    avg_cost: float        # precio promedio de compra, en la moneda del instrumento
    opened_at: Optional[date] = None

    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost


@dataclass
class Quote:
    """Cotización de un instrumento en una fecha. `is_sample` marca datos de ejemplo."""
    ticker: str
    price: float
    as_of: date
    currency: str = "USD"
    is_sample: bool = False


@dataclass
class Fundamentals:
    """Fundamentales de una empresa. Campos opcionales: un proveedor puede no darlos."""
    ticker: str
    pe_ttm: Optional[float] = None
    eps: Optional[float] = None           # EPS reportado (último ejercicio anual, USD por ADR)
    eps_basis: Optional[str] = None       # base del EPS: reported_annual | ttm | normalized | forward
    eps_source: Optional[str] = None      # procedencia del EPS: edgar | yahoo:quote | ...
    fallback_sources: Optional[str] = None  # qué campos vinieron de fallback y de dónde/cuándo
    eps_consistent: Optional[bool] = None  # identidad EPS×acciones≈utilidad neta (SÓLO si NI reportado)
    eps_check_ratio: Optional[float] = None  # EPS×acciones / utilidad neta (≈1 si coherente)
    consistency_independent: bool = False  # True sólo si la consistencia compara NI REPORTADO (no reconstruido)
    ni_reconstructed: bool = False        # utilidad neta reconstruida de EPS×acciones (etiqueta directa ausente)
    ni_source_concept: Optional[str] = None  # concepto EDGAR de la utilidad neta (o "reconstruido: ...")
    ni_period: Optional[str] = None       # período fiscal de la utilidad neta usada
    shares_source: Optional[str] = None   # procedencia de las acciones vigentes usadas en market cap
    # --- TTM y balance (Fase 3A C/D) ---
    eps_annual: Optional[float] = None    # EPS diluido del último ejercicio anual (USD por ADR)
    eps_ttm: Optional[float] = None       # EPS diluido TTM (4 trimestres de 3m, split-safe)
    eps_ttm_method: Optional[str] = None  # suma_eps_trimestral | utilidad_neta/acciones_vigentes
    eps_ttm_window: Optional[str] = None  # ventana fiscal de los 4 trimestres usados
    ttm_vs_annual_ratio: Optional[float] = None  # EPS_TTM / EPS_anual (cross-check, ≈1 si equivalente)
    fcf_annual: Optional[float] = None    # FCF anual (USD): OCF − CAPEX del ejercicio
    fcf_ttm: Optional[float] = None       # FCF TTM (USD): ΣOCF_3m − ΣCAPEX_3m de 4 trimestres
    diluted_shares: Optional[float] = None  # acciones promedio ponderadas diluidas (período de ref.)
    gross_debt: Optional[float] = None    # deuda bruta (corto + largo plazo), divisa de reporte
    cash_and_sti: Optional[float] = None  # efectivo + inversiones de corto plazo
    net_debt: Optional[float] = None      # deuda neta = deuda bruta − efectivo
    gross_margin: Optional[float] = None  # utilidad bruta / ingresos
    operating_margin: Optional[float] = None  # resultado operativo / ingresos
    eps_ttm_denominator: Optional[float] = None  # acciones diluidas usadas en EPS_TTM (y su período)
    eps_ttm_pershare_check: Optional[float] = None  # EPS_TTM(NI/acciones) / EPS_TTM(identidad por-acción) ≈1
    data_quality: str = "ok"              # ok | sospechoso | bloqueado (guard de plausibilidad)
    quality_reason: Optional[str] = None  # por qué se marcó sospechoso/bloqueado
    pe_forward: Optional[float] = None
    ev_ebitda: Optional[float] = None
    fcf_yield: Optional[float] = None     # free cash flow / market cap
    roic: Optional[float] = None
    roe: Optional[float] = None
    rev_growth_yoy: Optional[float] = None
    eps_growth_yoy: Optional[float] = None
    net_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    market_cap: Optional[float] = None
    currency: Optional[str] = None        # divisa de reporte (EDGAR): USD, EUR, TWD, ...
    as_of: Optional[str] = None           # fin del último periodo anual usado (YYYY-MM-DD)
    taxonomy: Optional[str] = None        # us-gaap | ifrs-full (procedencia)
    is_sample: bool = False


@dataclass
class ETFHolding:
    """Un componente dentro de un ETF, con su peso (0-1)."""
    ticker: str
    weight: float
    name: Optional[str] = None
    sector: Optional[str] = None


@dataclass
class RiskLimits:
    """Restricciones del inversor. El motor de decisiones debe respetarlas."""
    max_weight_per_asset: float = 0.25     # 25% máx por activo individual
    max_weight_per_sector: float = 0.40    # 40% máx por sector
    min_cash: float = 0.0                  # liquidez mínima a conservar (fracción)
    risk_tolerance: str = "moderate"       # conservative | moderate | aggressive
    horizon_years: float = 15.0


@dataclass
class FactorScore:
    """Puntajes factoriales de un instrumento (0-100 cada uno). Marcados si es sample."""
    ticker: str
    value: float = 0.0
    quality: float = 0.0
    growth: float = 0.0
    momentum: float = 0.0
    low_risk: float = 0.0
    composite: float = 0.0
    is_sample: bool = False
    detail: dict = field(default_factory=dict)
