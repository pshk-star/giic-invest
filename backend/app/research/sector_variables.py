"""P1.7.2 — MATRIZ DE VARIABLES SECTORIALES para NVDA/META/NFLX/TSM/ASML.

Cada variable lleva: hipótesis económica, fuente VERIFICABLE, frecuencia, fecha de disponibilidad,
línea financiera que mueve, tratamiento cuando falta, y `obtenible` = si HOY podemos obtenerla y
MANTENERLA con nuestras fuentes (EODHD, EDGAR, FRED PIT, pit_snapshots). Nada decorativo: solo las
`obtenible=True` se cablean al motor; las demás quedan documentadas como NO mantenidas (honestidad).

Esto es deliberadamente CONSERVADOR: la mayoría de variables operativas de sector (capex de
hyperscalers, book-to-bill, utilización de obleas, ARPU, precio por anuncio) NO están disponibles a
calidad point-in-time en nuestras fuentes pagadas actuales, así que se marcan NO obtenibles en vez
de fingir una señal.
"""
from __future__ import annotations

from typing import Dict, List

# Campos de cada variable (contrato):
#   hypothesis, source, frequency, availability, financial_line, missing, obtainable
def V(hypothesis, source, frequency, availability, financial_line, missing, obtainable):
    return {"hypothesis": hypothesis, "source": source, "frequency": frequency,
            "availability": availability, "financial_line": financial_line,
            "missing": missing, "obtainable": obtainable}


# --- Variables TRANSVERSALES realmente obtenibles y mantenibles ---
_OBTAINABLE_COMMON = {
    "revisiones_consenso_ingresos": V(
        "Revisiones al alza del consenso de ingresos anticipan mayor crecimiento proyectado.",
        "EODHD Earnings.Trend → pit_snapshots (estimate:revenue, revisions)", "semanal/mensual",
        "captura propia (captured_at); histórico PIT crece desde ahora",
        "ingresos (senda g años 1-2)", "sin revisión: se mantiene el consenso vigente", True),
    "revisiones_consenso_eps": V(
        "Revisiones de EPS informan el margen/beneficio esperado (reconciliado, no directo).",
        "EODHD Earnings.Trend → pit_snapshots (estimate:eps, trend 7/30/60/90)", "semanal/mensual",
        "captura propia", "margen EBIT (vía reconciliación EPS→EBIT)",
        "sin revisión: margen = m0 reportado", True),
    "rf_moneda": V(
        "La tasa libre de riesgo por moneda mueve WACC y el techo del crecimiento terminal.",
        "FRED PIT (DGS10) y proxies EUR/TWD documentados", "diaria",
        "vintage FRED (release_date<=as_of)", "WACC y g_terminal",
        "sin dato: se usa el rf fechado del supuesto de mercado", True),
    "fx_a_usd": V(
        "El tipo de cambio traslada el equity local a USD (TSM TWD, ASML EUR).",
        "tasa fechada en MARKET_2026_11_10 (FX); actualizable", "diaria",
        "fecha de la tasa", "puente EV→equity (ps_usd)",
        "sin dato: se usa la última tasa fechada", True),
}

# --- Variables operativas de sector: hipótesis válida, pero HOY NO obtenibles/mantenibles ---
def _not_obtainable(hyp, line, why):
    return V(hyp, "no disponible PIT en EODHD/EDGAR/FRED", "n/a", "n/a", line,
             "no se cablea; se documenta la ausencia", False)


SECTOR_VARIABLES: Dict[str, Dict[str, dict]] = {
    "NVDA": {
        **_OBTAINABLE_COMMON,
        "capex_hyperscalers": _not_obtainable(
            "El capex agregado de hyperscalers en IA empuja la demanda de GPU y los ingresos de NVDA.",
            "ingresos", "requiere agregación PIT de guías de MSFT/GOOGL/AMZN/META, no estructurada en nuestras fuentes"),
        "restricciones_exportacion": _not_obtainable(
            "Controles de exportación a China recortan mercado direccionable y márgenes.",
            "ingresos/margen", "evento regulatorio no estructurado; no serie PIT"),
    },
    "TSM": {
        **_OBTAINABLE_COMMON,
        "book_to_bill_semis": _not_obtainable(
            "Book-to-bill del sector anticipa el ciclo de pedidos y la utilización de capacidad.",
            "ingresos", "no hay serie PIT mantenible en nuestras fuentes"),
        "utilizacion_capacidad": _not_obtainable(
            "La utilización de obleas mueve el margen bruto por apalancamiento operativo.",
            "margen EBIT", "dato operativo trimestral sin serie PIT estructurada"),
    },
    "ASML": {
        **_OBTAINABLE_COMMON,
        "pedidos_backlog_euv": _not_obtainable(
            "Los pedidos/backlog de litografía EUV anticipan ingresos a 1-2 años.",
            "ingresos", "cifra de guidance no estructurada PIT en nuestras fuentes"),
    },
    "META": {
        **_OBTAINABLE_COMMON,
        "precio_por_anuncio": _not_obtainable(
            "Precio por anuncio × impresiones explica el crecimiento de ingresos de publicidad.",
            "ingresos", "KPI operativo no disponible como serie PIT"),
        "capex_ia_retorno": _not_obtainable(
            "El capex en infraestructura de IA presiona el FCF y el margen a corto.",
            "reinversión/margen", "parcial en 10-K/8-K; no serie PIT mantenible automáticamente"),
    },
    "NFLX": {
        **_OBTAINABLE_COMMON,
        "arpu_suscriptores": _not_obtainable(
            "ARPU × suscriptores y la publicidad explican el crecimiento de ingresos.",
            "ingresos", "KPI operativo trimestral sin serie PIT estructurada"),
        "inversion_contenido": _not_obtainable(
            "La amortización de contenido vive en el OCF y condiciona el FCFF.",
            "reinversión/FCFF", "parcial en estados; ya tratado por ruta OCF en fcff_inputs, no como variable sectorial PIT"),
    },
}


def obtainable_for(ticker: str) -> List[str]:
    return [k for k, v in SECTOR_VARIABLES.get(ticker, {}).items() if v.get("obtainable")]


def wired_variables() -> List[str]:
    """Variables realmente cableadas al motor (transversales obtenibles)."""
    return sorted(_OBTAINABLE_COMMON.keys())
