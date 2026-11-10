"""P1.8.1 — AUDITORÍA ESTADÍSTICA del backtest existente (pura, testeable). No crea modelos nuevos.

Opera sobre los puntos crudos volcados por forecast_backtest (--dump). Corrige las debilidades de
P1.8:
  - error de FCFF escalado por ingresos / WAPE / acumulado (el error relativo explota con FCFF≈0/neg),
  - métricas por componente (ingresos, margen, EBIT, reinversión, FCFF) por separado,
  - independencia (totales vs unidades independientes),
  - comparación emparejada A/C/D con bootstrap por CLUSTER de empresa (respeta dependencia).
No elimina observaciones: diagnostica el efecto del denominador ≈0 mostrando con/sin, sin borrarlas.
"""
from __future__ import annotations

import random
from collections import defaultdict
from statistics import median
from typing import Dict, List, Optional

random.seed(42)


def _abs_error(pt: dict, comp: str) -> Optional[float]:
    """Error ABSOLUTO del componente, en escala comparable:
       revenue -> relativo (|f/a-1|); margin -> |pp|; ebit/reinvest/fcff -> |f-a|/|rev_a| (escala estable)."""
    f, a = pt.get(f"{comp}_f"), pt.get(f"{comp}_a")
    rev = pt.get("rev_a")
    if f is None or a is None:
        return None
    if comp == "rev":
        return abs(f / a - 1.0) if a else None
    if comp == "margin":
        return abs(f - a)
    if rev and rev > 0:
        return abs(f - a) / rev
    return None


def _signed_error(pt: dict, comp: str) -> Optional[float]:
    f, a = pt.get(f"{comp}_f"), pt.get(f"{comp}_a")
    rev = pt.get("rev_a")
    if f is None or a is None:
        return None
    if comp == "rev":
        return (f / a - 1.0) if a else None
    if comp == "margin":
        return f - a
    return (f - a) / rev if (rev and rev > 0) else None


def independence(points: List[dict]) -> dict:
    per_model = defaultdict(int)
    for p in points:
        per_model[p["model"]] += 1
    companies = {p["ticker"] for p in points}
    units_cby = {(p["ticker"], p["base_year"]) for p in points}        # ignora solape de horizonte
    units_c = companies
    return {"total_obs": len(points), "por_modelo": dict(per_model),
            "empresas": len(companies), "unidades_empresa_x_año_base": len(units_cby),
            "nota": ("las obs comparten camino (h1/h2/h3 del mismo año base) y años base consecutivos "
                     "se solapan: la unidad independiente es ~empresa×año base, y a efectos de "
                     "incertidumbre, la EMPRESA (cluster). N_total sobreestima la información real.")}


def component_metrics(points: List[dict], model: str, comp: str, h: Optional[int] = None) -> dict:
    sub = [p for p in points if p["model"] == model and (h is None or p["h"] == h)]
    ae = [_abs_error(p, comp) for p in sub]
    ae = [x for x in ae if x is not None]
    se = [_signed_error(p, comp) for p in sub]
    se = [x for x in se if x is not None]
    out = {"n": len(ae)}
    if ae:
        out["mae"] = round(median(ae), 4)      # mediana del error (escala del componente)
        out["bias"] = round(median(se), 4)
    # WAPE y error relativo clásico solo para componentes con denominador agregable
    fa = [(p.get(f"{comp}_f"), p.get(f"{comp}_a")) for p in sub]
    fa = [(f, a) for f, a in fa if f is not None and a is not None]
    if fa:
        num = sum(abs(f - a) for f, a in fa)
        den = sum(abs(a) for f, a in fa)
        out["wape"] = round(num / den, 4) if den > 0 else None
        if comp == "fcff":
            # diagnóstico del denominador ≈0 (sin borrar): fracción con |fcff_a|<5% de ingresos
            nz = [p for p in sub if p.get("fcff_a") is not None and p.get("rev_a")
                  and abs(p["fcff_a"]) < 0.05 * p["rev_a"]]
            rel = [abs(p["fcff_f"] / p["fcff_a"] - 1.0) for p in sub
                   if p.get("fcff_a") and p.get("fcff_f") is not None]
            rel_big = [abs(p["fcff_f"] / p["fcff_a"] - 1.0) for p in sub
                       if p.get("fcff_a") and p.get("fcff_f") is not None
                       and p.get("rev_a") and abs(p["fcff_a"]) >= 0.05 * p["rev_a"]]
            out["rel_error_clasico"] = round(median(rel), 4) if rel else None
            out["rel_error_sin_denominador_casi_cero"] = round(median(rel_big), 4) if rel_big else None
            out["frac_fcff_casi_cero"] = round(len(nz) / len(sub), 3) if sub else None
    return out


def cumulative_fcff(points: List[dict], model: str) -> dict:
    """Error de FCFF ACUMULADO a 3 años por (empresa, año base) con h=1,2,3 completos.
    Escalado por ingresos acumulados (denominador estable y positivo)."""
    by = defaultdict(dict)
    for p in points:
        if p["model"] == model and p.get("fcff_f") is not None and p.get("fcff_a") is not None:
            by[(p["ticker"], p["base_year"])][p["h"]] = p
    errs, rel = [], []
    for key, hs in by.items():
        if all(h in hs for h in (1, 2, 3)):
            cf = sum(hs[h]["fcff_f"] for h in (1, 2, 3))
            ca = sum(hs[h]["fcff_a"] for h in (1, 2, 3))
            crev = sum(hs[h]["rev_a"] for h in (1, 2, 3))
            if crev > 0:
                errs.append(abs(cf - ca) / crev)
            if ca != 0:
                rel.append(cf / ca - 1.0)
    return {"n": len(errs),
            "mae_escalado_ingresos": round(median(errs), 4) if errs else None,
            "bias_rel": round(median(rel), 4) if rel else None}


def paired_cluster_bootstrap(points: List[dict], m1: str, m2: str, comp: str,
                             nb: int = 2000) -> dict:
    """Diferencia emparejada de |error| (m1−m2) en puntos COMUNES (misma empresa/año base/horizonte),
    con bootstrap por CLUSTER de empresa (respeta dependencia temporal e intra-empresa)."""
    idx = defaultdict(dict)
    for p in points:
        idx[(p["ticker"], p["base_year"], p["h"])][p["model"]] = p
    by_co = defaultdict(list)
    for key, md in idx.items():
        if m1 in md and m2 in md:
            e1, e2 = _abs_error(md[m1], comp), _abs_error(md[m2], comp)
            if e1 is not None and e2 is not None:
                by_co[key[0]].append(e1 - e2)
    cos = list(by_co.keys())
    alld = [d for co in cos for d in by_co[co]]
    if len(alld) < 10 or len(cos) < 3:
        return {"n_pairs": len(alld), "n_companies": len(cos), "insuficiente": True}
    point = sum(alld) / len(alld)
    means = []
    for _ in range(nb):
        samp = [random.choice(cos) for _ in cos]              # resamplea EMPRESAS enteras
        ds = [d for co in samp for d in by_co[co]]
        if ds:
            means.append(sum(ds) / len(ds))
    means.sort()
    lo, hi = means[int(0.05 * nb)], means[int(0.95 * nb)]
    return {"n_pairs": len(alld), "n_companies": len(cos),
            "mean_diff_abs_error": round(point, 5), "ci90": [round(lo, 5), round(hi, 5)],
            "significativo": bool(lo > 0 or hi < 0),
            "mejor": (m2 if point > 0 else m1) if (lo > 0 or hi < 0) else "empate"}
