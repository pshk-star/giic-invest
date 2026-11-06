"""Features fundamentales POINT-IN-TIME: de-acumulación YTD -> trimestral y disponibilidad.

Problema (auditoría): ~1/3 de los conceptos de flujo vienen como ACUMULADO YTD (p.ej.
ingresos de 9 meses en el 10-Q del Q3). Usarlos como trimestrales distorsiona márgenes y
crecimiento. Aquí se reconstruye el valor TRIMESTRAL: si existe el hecho nativo de ~3
meses se usa; si solo hay YTD, se de-acumula (YTD_q − YTD_{q-1} dentro del mismo año fiscal).

Cada valor trimestral hereda la MAYOR filing_date de los hechos usados (disponibilidad real).
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional


def _days(a: str, b: str) -> int:
    ya, ma, da = map(int, a.split("-")); yb, mb, db = map(int, b.split("-"))
    return (date(yb, mb, db) - date(ya, ma, da)).days


def span_days(ps: Optional[str], pe: str) -> Optional[int]:
    return _days(ps, pe) if ps else None


def is_quarterly(ps: Optional[str], pe: str) -> bool:
    d = span_days(ps, pe)
    return d is not None and 60 <= d <= 100


def is_ytd(ps: Optional[str], pe: str) -> bool:
    d = span_days(ps, pe)
    return d is not None and d > 100


def quarterly_values(facts: List[dict]) -> List[dict]:
    """Devuelve valores TRIMESTRALES {period_end, value, filing_date, fiscal_year} para un
    concepto de flujo de UN ticker. `facts`: dicts con period_start, period_end, value,
    filing_date, fiscal_period/fiscal_year. Prefiere hechos nativos de 3m; de-acumula YTD.

    Usa SOLO la última versión conocida por periodo (mayor filing_date) para el valor, pero
    conserva esa filing_date como disponibilidad (el consumidor filtra filing_date<=as_of).
    """
    from collections import defaultdict
    # Por año fiscal (año del period_end): hechos nativos (~3m) y YTD, última versión por fecha.
    by_fy: Dict[str, Dict[str, Dict[str, dict]]] = defaultdict(lambda: {"native": {}, "ytd": {}})
    for f in facts:
        pe, ps = f.get("period_end"), f.get("period_start")
        if f.get("value") is None or not pe:
            continue
        bucket = None
        if is_quarterly(ps, pe):
            bucket = "native"
        elif is_ytd(ps, pe):
            bucket = "ytd"
        if bucket is None:
            continue
        d = by_fy[pe[:4]][bucket]
        cur = d.get(pe)
        if cur is None or (f.get("filing_date") or "") > (cur.get("filing_date") or ""):
            d[pe] = f

    out: List[dict] = []
    for fy, d in by_fy.items():
        ends = sorted(set(d["native"]) | set(d["ytd"]))
        run = 0.0  # suma trimestral acumulada del FY (para de-acumular YTD)
        for pe in ends:
            if pe in d["native"]:
                f = d["native"][pe]; qval = float(f["value"]); src = "native_q"
            else:
                f = d["ytd"][pe]; qval = float(f["value"]) - run; src = "from_ytd"
            run += qval
            out.append({"period_end": pe, "value": qval,
                        "filing_date": f.get("filing_date"), "source": src})
    out.sort(key=lambda x: x["period_end"])
    return out


def growth_yoy(quarterly: List[dict]) -> List[dict]:
    """Crecimiento interanual trimestre vs mismo trimestre del año anterior (4 periodos atrás)."""
    out = []
    for i in range(4, len(quarterly)):
        a, b = quarterly[i - 4]["value"], quarterly[i]["value"]
        if a and a != 0:
            out.append({"period_end": quarterly[i]["period_end"], "value": b / abs(a) - 1.0,
                        "filing_date": quarterly[i]["filing_date"]})
    return out
