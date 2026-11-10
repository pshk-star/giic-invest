"""P1.7.2 — Reporte experimental reproducible: FCFF P1.6 vs prospectivo (consenso/GIIC/combinado)
para NVDA/META/NFLX/TSM/ASML, con atribución por bloque (crecimiento/márgenes/reinversión/WACC).

Base = datos REPORTADOS (EDGAR/EODHD, verificados en P1.5.1-A/P1.6), embebidos como constantes para
reproducibilidad. Consenso = EODHD vivo (valora HOY; permitido por #7). Motor P1.6 intacto como
benchmark. NO se calibra a Morningstar/mercado. NO toca Fair Value productivo ni Advisor.

Uso: python -m app.research.fcff_forward_report            # usa EODHD si hay EODHD_API_KEY
     python -m app.research.fcff_forward_report --no-net   # solo B/P1.6 (sin consenso)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, Optional

from datetime import date

from .fcff_forward import Assump, Base, value_p16, value_path, attribute_fv, FX, ADR
from .forward_forecast import (Consensus, consensus_path, giic_path, combined_path)
from .consensus_admission import Reported, admit_consensus

# Datos REPORTADOS (de fcff_base_full, P1.6). ebit_margin0 = ebit/revenue.
BASE: Dict[str, Base] = {
    "NVDA": Base("NVDA", "USD", 215938e6, 130387/215938, -2137e6, 24514e6, 0.151, 0.0, 1),
    "META": Base("META", "USD", 200966e6, 83276/200966, 22871e6, 2574e6, 0.2964, 1090e6, 1),
    "NFLX": Base("NFLX", "USD", 45183.036e6, 13326.603/45183.036, 6000e6, 4344e6, 0.137, 604.051e6, 1),
    "TSM":  Base("TSM", "TWD", 3809054e6, 1935645/3809054, -1703273.299e6, 25927.6e6, 0.1598, 12370.4e6, 5),
    "ASML": Base("ASML", "EUR", 32667.3e6, 11301.4/32667.3, -8525.1e6, 388.9e6, 0.1765, 0.0, 1),
}
ASSUMP: Dict[str, Assump] = {
    "NVDA": Assump(1.35, 0.048, 0.02, 0.15, 2.7, 0.30, 0.45, 0.22),
    "META": Assump(1.20, 0.050, 0.08, 0.14, 1.3, 0.15, 0.38, 0.20),
    "NFLX": Assump(1.10, 0.053, 0.12, 0.14, 2.0, 0.12, 0.30, 0.18),
    "TSM":  Assump(1.15, 0.023, 0.03, 0.16, 0.8, 0.18, 0.42, 0.18),
    "ASML": Assump(1.25, 0.030, 0.05, 0.175, 2.2, 0.14, 0.38, 0.25),
}
PX = {"NVDA": 177.20, "META": 610.15, "NFLX": 63.41, "TSM": 375.44, "ASML": 1424.75}
RF = {"USD": 0.041, "EUR": 0.026, "TWD": 0.015}
# Fin del último ejercicio reportado (ancla de escala del gate). NVDA cierra en enero.
FY_END = {"NVDA": "2026-01-31", "META": "2025-12-31", "NFLX": "2025-12-31",
          "TSM": "2025-12-31", "ASML": "2025-12-31"}
TICKERS = ["NVDA", "META", "NFLX", "TSM", "ASML"]


def _trend_list(obj: dict) -> list:
    trend = (obj.get("Earnings", {}) or {}).get("Trend", {}) or {}
    out = []
    for k, d in trend.items():
        d = d or {}

        def n(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None
        out.append({"date": d.get("date") or k, "period": d.get("period"),
                    "revEstAvg": n(d.get("revenueEstimateAvg")), "revGrowth": n(d.get("revenueEstimateGrowth")),
                    "revAnalysts": n(d.get("revenueEstimateNumberOfAnalysts")),
                    "epsEstAvg": n(d.get("earningsEstimateAvg")), "epsAnalysts": n(d.get("earningsEstimateNumberOfAnalysts"))})
    return out


def _reported(t: str) -> Reported:
    b = BASE[t]
    ni = b.revenue * b.ebit_margin0 * (1 - b.tax_rate)   # proxy; sólo para net-margin sanity
    return Reported(ccy=b.ccy, revenue=b.revenue, shares=b.shares, ni=ni,
                    ebit_margin0=b.ebit_margin0, interest=b.interest, tax_rate=b.tax_rate,
                    fiscal_year_end=FY_END[t])


def _resolve(t: str):
    if not os.getenv("EODHD_API_KEY"):
        return None
    try:
        from app.core.connectors.eodhd import EodhdFundamentalsConnector
        conn = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
        _s, _a, obj = conn._resolve(t)
        return obj
    except Exception:
        return None


def evaluate(t: str, use_net: bool = True, today: Optional[date] = None) -> dict:
    base, a = BASE[t], ASSUMP[t]
    gT = RF[base.ccy]
    today = today or date.today()
    out: dict = {"ticker": t, "ccy": base.ccy, "price": PX[t], "gT": gT}
    # B = GIIC propio = P1.6 (benchmark)
    vB = value_p16(base, a)
    out["fv_P16_GIIC"] = round(vB["bridge"]["ps_usd"], 2)
    out["terminal_weight_P16"] = round(vB["proj"]["terminal_weight"], 3)
    pB = giic_path(base, a, gT)

    obj = _resolve(t) if use_net else None
    if obj is None:
        out["fv_consenso"] = None
        out["note"] = "sin consenso (sin red o sin EODHD_API_KEY): solo P1.6/GIIC"
        return out
    # Control de moneda a nivel objeto
    ccy = ((obj.get("General", {}) or {}).get("CurrencyCode"))
    updated = (obj.get("General", {}) or {}).get("UpdatedAt")
    if ccy and ccy != base.ccy:
        out["fv_consenso"] = None
        out["gate"] = {"admitted": False, "reasons": [f"moneda EODHD {ccy} ≠ {base.ccy}"]}
        return out
    # GATE: seleccionar por fecha + validar
    gate = admit_consensus(t, _trend_list(obj), _reported(t), today, updated)
    out["gate"] = gate
    if not gate["admitted"]:
        out["fv_consenso"] = None
        out["note"] = "consenso NO admitido por el gate → solo P1.6/GIIC (ver gate.reasons)"
        return out
    # A = consenso VALIDADO (construye Consensus desde el gate)
    cyd, nyd = gate["cy"], gate.get("ny") or {}
    c = Consensus(currency=base.ccy, g_cy=cyd["rev_growth"], g_ny=nyd.get("rev_growth"),
                  eps_cy=cyd["eps"], eps_ny=nyd.get("eps"), n_analysts=cyd["n_analysts"],
                  rev_cy=cyd["rev_level"], rev_ny=nyd.get("rev_level"),
                  fiscal_cy_end=cyd["fiscal_end"], fiscal_ny_end=nyd.get("fiscal_end"))
    pA = consensus_path(base, a, c, gT)
    if not pA.get("available"):
        out["fv_consenso"] = None
        out["consenso_no_disponible"] = pA.get("reason")
        return out
    vA = value_path(base, a, pA["g"], pA["m"], gT=gT)
    out["fv_consenso"] = round(vA["bridge"]["ps_usd"], 2)
    out["confianza_consenso"] = gate["confidence"]
    out["procedencia_consenso"] = pA["provenance"]
    out["notas_consenso"] = pA["notes"]
    out["atribucion_consenso_vs_P16"] = attribute_fv(base, a, pA["g"], pA["m"], gT_new=gT)
    # C = combinado (solo si A admitido)
    pC = combined_path(pA, pB, a.years)
    if pC.get("available"):
        vC = value_path(base, a, pC["g"], pC["m"], gT=gT)
        out["fv_combinado"] = round(vC["bridge"]["ps_usd"], 2)
        out["atribucion_combinado_vs_P16"] = attribute_fv(base, a, pC["g"], pC["m"], gT_new=gT)
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--no-net", action="store_true")
    p.add_argument("--tickers", nargs="*")
    args = p.parse_args(argv)
    ts = [t.upper() for t in args.tickers] if args.tickers else TICKERS
    res = {t: evaluate(t, use_net=not args.no_net) for t in ts}
    print(json.dumps({"experimental": True, "no_calibrado_a_mercado": True,
                      "benchmark": "fv_P16_GIIC (motor P1.6 intacto)", "resultados": res},
                     ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
