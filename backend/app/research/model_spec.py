"""Especificaciones de modelo CONGELADAS para la emisión prospectiva experimental.

Cambiar un modelo = subir su `version` (nunca editar en caliente una versión ya emitida).
Las predicciones guardan `model_version` + `features_version` + `data_ref`, de modo que
cada emisión es reproducible y auditable. Ninguno está validado.
"""
from __future__ import annotations

STATUS = "EXPERIMENTAL_NO_VALIDADO"
FEATURES_VERSION = "feat-1.0.0"
CALENDAR = "XNYS"

# Orden EXACTO de features (congelado).
PRICE_FEATURES = ["mom_12_1", "ret_20", "ret_60", "ret_120", "reversal_5",
                  "vol_20", "vol_60", "dd_252", "vol_ratio", "rel_strength_60"]
FUND_FEATURES = ["rev_g", "ni_g", "accel", "net_margin", "roe", "leverage", "fcf_margin"]

MODEL_A = {
    "name": "price-ridge",
    "version": "a-1.0.0",
    "feature_set": "price",
    "features": PRICE_FEATURES,
    "estimator": "Ridge(alpha=1.0, standardized)",
    "alpha": 1.0,
    "horizons_sessions": [20, 60, 252],   # A = benchmark experimental
    "target": "retorno relativo al mercado (equiponderado)",
}

MODEL_B = {
    "name": "price-fund-ridge",
    "version": "b-1.0.0",
    "feature_set": "price+fundamentals_pit",
    "features": PRICE_FEATURES + FUND_FEATURES,
    "estimator": "Ridge(alpha=1.0, standardized)",
    "alpha": 1.0,
    "horizons_sessions": [252],            # B = candidato experimental (sin superioridad probada)
    "target": "retorno relativo al mercado (equiponderado)",
}

MODELS = [MODEL_A, MODEL_B]
