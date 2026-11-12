"""Conciliación TRIMESTRAL NVDA: ¿EODHD y SEC usan los MISMOS 4 trimestres? (items 1,2,4,5).

Método robusto: cada trimestre se deriva de los ACUMULADOS YTD del mismo año fiscal (Q = YTD_n − YTD_{n-1};
Q1 = YTD_3m; Q4 = FY − YTD_9m). Así se evita mezclar ventanas. Se alinea con los trimestres de EODHD por
fecha de cierre y se suma el TTM de la MISMA ventana. Muestra por trimestre: inicio, fin, formulario,
fecha de publicación y concepto XBRL. Read-only. Companyfacts = EDGAR (NO es independiente); IR es el
árbitro final (se señala).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.research.ttm import _cls, _dur, _d

VALID = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquireProductiveAssets", "PaymentsToAcquirePropertyPlantAndEquipment"],
}
EOD_Q = {"revenue": ["totalRevenue"], "operating_income": ["operatingIncome", "ebit"],
         "net_income": ["netIncome"], "ocf": ["totalCashFromOperatingActivities"], "capex": ["capitalExpenditures"]}


def _facts_periods(usg, concept):
    node = (usg or {}).get(concept) or {}
    out = {}
    for unit, rows in (node.get("units", {}) or {}).items():
        for f in rows:
            s, e, v = f.get("start"), f.get("end"), f.get("val")
            if v is None or not e or not s or (f.get("form") or "") not in VALID:
                continue
            k = (s, e)
            if k not in out or (f.get("filed") or "") > (out[k]["filed"] or ""):
                out[k] = {"start": s, "end": e, "val": float(v), "filed": f.get("filed"),
                          "form": f.get("form"), "days": _dur(s, e), "accn": f.get("accn")}
    return sorted(out.values(), key=lambda x: (x["start"], x["end"]))


def quarters_from_ytd(periods, concept):
    """Deriva trimestres individuales de los acumulados YTD agrupados por inicio de año fiscal."""
    by_start: Dict[str, list] = {}
    for p in periods:
        if p["days"] and 80 <= p["days"] <= 400:    # YTD acumulado (3m..FY)
            by_start.setdefault(p["start"], []).append(p)
    q: Dict[str, dict] = {}
    for start, ps in by_start.items():
        ps = sorted(ps, key=lambda x: x["end"])
        prev = None
        for p in ps:
            if prev is None:
                val = p["val"]; src = f"YTD-3m ({p['days']}d)"
            else:
                val = p["val"] - prev["val"]; src = f"{p['days']}d − {prev['days']}d"
            q[p["end"]] = {"val": val, "q_end": p["end"], "derivado": src, "form": p["form"],
                           "filed": p["filed"], "concepto": concept, "ytd_start": start}
            prev = p
    return q


def sec_quarters(usg, metric):
    for c in CONCEPTS[metric]:
        pers = _facts_periods(usg, c)
        if pers:
            q = quarters_from_ytd(pers, c)
            if q:
                return q, c
    return {}, None


def eod_quarters(obj, metric):
    fin = (obj or {}).get("Financials", {}) or {}
    state = "Cash_Flow" if metric in ("ocf", "capex") else "Income_Statement"
    qd = (fin.get(state, {}) or {}).get("quarterly", {}) or {}
    def num(d, keys):
        for k in keys:
            v = (d or {}).get(k)
            if v not in (None, "", "None"):
                try: return float(v)
                except: pass
        return None
    out = {}
    for date_k, row in qd.items():
        v = num(row, EOD_Q[metric])
        if v is not None:
            out[date_k[:10]] = v
    return out


def run():
    from app.providers.edgar import EDGARProvider
    prov = EDGARProvider(user_agent=os.getenv("EDGAR_USER_AGENT") or "GIIC research noreply@giic.example")
    prov._load_ciks()
    facts = prov._facts("NVDA")
    usg = (facts.get("facts", {}) or {}).get("us-gaap", {}) or {}
    eod_obj = {}
    if os.getenv("EODHD_API_KEY"):
        from app.core.connectors.eodhd import EodhdFundamentalsConnector
        c = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
        _s, _a, eod_obj = c._resolve("NVDA")

    # ventana TTM: 4 trimestres más recientes comunes. Ancla = trimestres SEC de OCF.
    sec_m = {m: sec_quarters(usg, m) for m in CONCEPTS}
    eod_m = {m: eod_quarters(eod_obj, m) for m in CONCEPTS}
    sec_ocf_q = sorted(sec_m["ocf"][0].keys())
    window = sec_ocf_q[-4:] if len(sec_ocf_q) >= 4 else sec_ocf_q

    table = {}
    for m in CONCEPTS:
        sq, sc = sec_m[m]
        eq = eod_m[m]
        # alinear EODHD a las fechas de la ventana (tolerancia ±7 días por cierres distintos)
        def eod_near(end):
            if end in eq:
                return eq[end], end
            te = _d(end)
            for k, v in eq.items():
                kd = _d(k)
                if kd and te and abs((kd - te).days) <= 7:
                    return v, k
            return None, None
        rows = []
        sec_sum = 0.0; eod_sum = 0.0; sec_ok = True; eod_ok = True
        for end in window:
            s = sq.get(end)
            e_v, e_k = eod_near(end)
            if s: sec_sum += s["val"]
            else: sec_ok = False
            if e_v is not None: eod_sum += e_v
            else: eod_ok = False
            rows.append({"q_end": end, "sec_val": s["val"] if s else None,
                         "sec_deriv": s["derivado"] if s else None, "sec_form": s["form"] if s else None,
                         "sec_filed": s["filed"] if s else None, "sec_concepto": s["concepto"] if s else None,
                         "eod_val": e_v, "eod_q": e_k})
        table[m] = {"concepto_sec": sc, "ventana": window, "trimestres": rows,
                    "ttm_sec": sec_sum if sec_ok else None, "ttm_eodhd": eod_sum if eod_ok else None,
                    "dif_rel": (abs(sec_sum - eod_sum) / max(1.0, abs(sec_sum)) if (sec_ok and eod_ok) else None)}
    return {"ventana_ttm": window, "metricas": table,
            "nota": "Companyfacts = EDGAR (no independiente). IR de NVDA es el árbitro final (press release "
                    "trimestral) — contraste numérico pendiente de descarga de IR."}


def main(argv=None):
    print(json.dumps(run(), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
