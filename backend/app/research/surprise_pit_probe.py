"""P1.7 Fase 2 — VERIFICACIÓN POINT-IN-TIME de las sorpresas de resultados (read-only).

Antes de usar EODHD Earnings.History en un backtest hay que demostrar qué representan
exactamente epsEstimate / epsActual / reportDate y si la integridad PIT se sostiene. Este
sondeo NO escribe nada: inspecciona la estructura cruda de las 5 y reporta evidencia para
clasificar cada ticker como PIT ESTRICTO o EXPLORATORIO.

Preguntas que responde con datos (no supuestos):
  1. ¿Hay reportDate por trimestre? (ancla temporal imprescindible)
  2. ¿Hay beforeAfterMarket? (determina la primera sesión operable)
  3. ¿epsEstimate está poblado de forma consistente en trimestres pasados?
  4. ¿La estimación parece consenso PRE-anuncio? (heurística: coincide con el último
     epsTrend del período en Earnings.Trend, no con epsActual).

CONVENCIÓN CONSERVADORA (documentada, aplicada en el backtest):
  - beforeAfterMarket == 'BeforeMarket' => disponible ese día; primera sesión operable =
    la SIGUIENTE sesión (no se puede operar al cierre con info del pre-apertura sin look-ahead
    intradía; usamos cierre-a-cierre, así que entramos al cierre de la sesión siguiente).
  - beforeAfterMarket == 'AfterMarket'  => primera sesión operable = la SIGUIENTE sesión.
  - desconocido / solo fecha            => conservador: primera sesión operable = la SIGUIENTE.
  En todos los casos la señal NO usa ninguna información del período que se predice.

Uso: python -m app.research.surprise_pit_probe
"""
from __future__ import annotations

import json
import os
import sys

from app.core.connectors.eodhd import EodhdFundamentalsConnector

TICKERS = ["NVDA", "META", "NFLX", "TSM", "ASML"]


def classify(hist: dict) -> dict:
    periods = sorted(hist.keys())
    n = len(periods)
    with_report = sum(1 for p in periods if (hist[p] or {}).get("reportDate"))
    with_bam = sum(1 for p in periods if (hist[p] or {}).get("beforeAfterMarket"))
    with_est = sum(1 for p in periods if (hist[p] or {}).get("epsEstimate") is not None)
    with_act = sum(1 for p in periods if (hist[p] or {}).get("epsActual") is not None)
    bam_vals: dict = {}
    for p in periods:
        v = (hist[p] or {}).get("beforeAfterMarket")
        if v:
            bam_vals[v] = bam_vals.get(v, 0) + 1
    usable = [p for p in periods if (hist[p] or {}).get("epsEstimate") is not None
              and (hist[p] or {}).get("epsActual") is not None
              and (hist[p] or {}).get("reportDate")]
    structural = len(usable) >= 12 and with_report >= 0.9 * max(1, with_act)
    # DISTINCIÓN HONESTA (corrección P1.7.2 #7):
    #  - epsActual en reportDate es un HECHO REPORTADO => PIT genuino.
    #  - reportDate presente => podemos anclar temporalmente la sorpresa.
    #  - PERO epsEstimate siendo el CONSENSO DISPONIBLE ANTES del anuncio NO está verificado:
    #    EODHD NO entrega un historial versionado del consenso; no podemos descartar que el
    #    estimate del endpoint sea un valor actualizado/retroactivo. Por tanto la SORPRESA es
    #    PIT en su componente 'actual' y en el drift de precio, pero el componente derivado del
    #    ESTIMATE (SUE, surprise%) es EXPLORATORIO hasta probar disponibilidad pre-anuncio.
    surprise_component = "PIT" if structural else "INCOMPLETO"
    consensus_preannounce = "NO_VERIFICADO"  # requiere fuente con historial versionado del consenso
    overall = "EXPLORATORIO"  # mientras el consenso pre-anuncio no se verifique, el modelo C es exploratorio
    return {
        "n_quarters": n, "range": [periods[0], periods[-1]] if periods else None,
        "with_reportDate": with_report, "with_beforeAfterMarket": with_bam,
        "beforeAfterMarket_values": bam_vals,
        "with_epsEstimate": with_est, "with_epsActual": with_act,
        "usable_structural_quarters": len(usable),
        "componente_sorpresa_actual_pit": surprise_component,
        "consenso_preanuncio": consensus_preannounce,
        "classification": overall,
        "reason": ("Estructura completa (reportDate+estimate+actual en >=12 trimestres): el ACTUAL "
                   "y el drift de precio son PIT; el ESTIMATE pre-anuncio NO está verificado "
                   "(EODHD no versiona el consenso) => clasificación global EXPLORATORIA."
                   if structural else "Falta reportDate/estimate/actual consistente => exploratorio."),
        "evidencia_requerida_para_pit_estricto": ("historial versionado del consenso con fecha de "
                   "disponibilidad por estimación (snapshot propio en pit_snapshots a futuro, o una "
                   "fuente que selle la fecha de cada revisión de consenso ANTES del reporte)."),
        "recent_samples": [{"period": p, **{k: (hist[p] or {}).get(k) for k in
                            ("reportDate", "beforeAfterMarket", "epsEstimate", "epsActual",
                             "epsDifference", "surprisePercent")}} for p in periods[-3:]],
    }


def main():
    key = os.getenv("EODHD_API_KEY", "")
    if not key:
        print(json.dumps({"error": "sin EODHD_API_KEY"}))
        return 0
    conn = EodhdFundamentalsConnector(api_key=key)
    out = {"convencion_conservadora": "primera sesión operable = SIGUIENTE sesión a reportDate",
           "tickers": {}}
    for t in TICKERS:
        try:
            sym, _adr, obj = conn._resolve(t)
            hist = ((obj or {}).get("Earnings", {}) or {}).get("History", {}) or {}
            out["tickers"][t] = {"symbol": sym, **classify(hist)} if hist else {"error": "sin History"}
        except Exception as e:
            out["tickers"][t] = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
