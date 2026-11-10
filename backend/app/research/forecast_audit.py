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


COMPONENTS = ["rev", "margin", "ebit", "reinv", "fcff"]


# ---------------------------------------------------------------------------
# P1.8.2 — descomposición causal EXACTA del error de FCFF.
# FCFF = Rev·m·(1−t) − R.  Error = FCFF_f − FCFF_a. Baseline = actual; efectos de primer orden
# + término de INTERACCIÓN explícito (remanente exacto, sin residual oculto).
# ---------------------------------------------------------------------------
def decompose_point(pt: dict) -> Optional[dict]:
    rev_f, rev_a = pt.get("rev_f"), pt.get("rev_a")
    m_f, m_a = pt.get("margin_f"), pt.get("margin_a")
    ebit_f, ebit_a = pt.get("ebit_f"), pt.get("ebit_a")
    reinv_f, reinv_a = pt.get("reinv_f"), pt.get("reinv_a")
    fcff_f, fcff_a = pt.get("fcff_f"), pt.get("fcff_a")
    if None in (rev_f, rev_a, m_f, m_a, ebit_f, ebit_a, reinv_f, reinv_a, fcff_f, fcff_a):
        return None
    if not (rev_a and rev_f and ebit_a and ebit_f):
        return None
    # tasa fiscal efectiva recuperada: NOPAT = FCFF + reinversión ; t = 1 − NOPAT/EBIT
    t_f = 1 - (fcff_f + reinv_f) / ebit_f
    t_a = 1 - (fcff_a + reinv_a) / ebit_a
    # efectos de primer orden (baseline actual)
    c_rev = m_a * (1 - t_a) * (rev_f - rev_a)              # ingresos (NOPAT via Rev)
    c_margin = rev_a * (1 - t_a) * (m_f - m_a)             # margen EBIT
    c_tax = rev_a * m_a * (-(t_f - t_a))                   # impuestos (mayor t ⇒ menor FCFF)
    c_reinv = -(reinv_f - reinv_a)                         # reinversión (mayor R ⇒ menor FCFF)
    total = fcff_f - fcff_a
    interaction = total - (c_rev + c_margin + c_tax + c_reinv)
    s = rev_a
    return {"rev": c_rev / s, "margin": c_margin / s, "tax": c_tax / s, "reinv": c_reinv / s,
            "interaction": interaction / s, "total": total / s}


def bias_decomposition(points: List[dict], model: str, horizon: Optional[int] = None) -> dict:
    sub = [p for p in points if p["model"] == model and (horizon is None or p["h"] == horizon)]
    decs = [d for d in (decompose_point(p) for p in sub) if d]
    if not decs:
        return {"n": 0}
    keys = ["rev", "margin", "tax", "reinv", "interaction", "total"]
    out = {"n": len(decs)}
    for k in keys:
        vals = [d[k] for d in decs]
        out[k] = {"mediana": round(median(vals), 4), "media": round(sum(vals) / len(vals), 4)}
    # reconciliación exacta: suma de componentes == total (por construcción)
    recon = [abs((d["rev"] + d["margin"] + d["tax"] + d["reinv"] + d["interaction"]) - d["total"]) for d in decs]
    out["max_error_reconciliacion"] = round(max(recon), 9)
    return out


def reinvestment_analysis(points: List[dict], model: str) -> dict:
    sub = [p for p in points if p["model"] == model and p.get("reinv_f") is not None
           and p.get("reinv_a") is not None and p.get("rev_a")]
    if not sub:
        return {"n": 0}
    diff = [(p["reinv_f"] - p["reinv_a"]) / p["rev_a"] for p in sub]       # >0 ⇒ sobreestima reinversión
    rf = [p["reinv_f"] / p["rev_a"] for p in sub]
    ra = [p["reinv_a"] / p["rev_a"] for p in sub]
    # composición del R real (como % de ingresos): capex, −D&A, ΔWC
    comp = [p for p in sub if p.get("capex_a") is not None and p.get("dna_a") is not None and p.get("wc_a") is not None]
    cx = [p["capex_a"] / p["rev_a"] for p in comp]
    dn = [p["dna_a"] / p["rev_a"] for p in comp]
    wc = [p["wc_a"] / p["rev_a"] for p in comp]
    s2c = [p["s2c_used"] for p in sub if p.get("s2c_used")]
    return {"n": len(sub),
            "reinv_f_pct_ingresos_mediana": round(median(rf), 4),
            "reinv_a_pct_ingresos_mediana": round(median(ra), 4),
            "sobreestimacion_mediana_pct_ingresos": round(median(diff), 4),
            "composicion_R_real_%ingresos": {"capex": round(median(cx), 4) if cx else None,
                                             "D&A": round(median(dn), 4) if dn else None,
                                             "deltaWC": round(median(wc), 4) if wc else None},
            "s2c_usado_mediana": round(median(s2c), 3) if s2c else None}


def bias_robustness(points: List[dict], model: str) -> dict:
    """Bias de FCFF escalado por ingresos (mediana del 'total' de la descomposición), robustez."""
    def med_total(pts):
        decs = [d for d in (decompose_point(p) for p in pts) if d]
        return round(median([d["total"] for d in decs]), 4) if decs else None
    base = [p for p in points if p["model"] == model]
    companies = sorted({p["ticker"] for p in base})
    loo = {}
    for c in companies:
        loo[c] = med_total([p for p in base if p["ticker"] != c])
    loo_vals = [v for v in loo.values() if v is not None]
    by_sector = {}
    for sec in sorted({p.get("sector", "Otro") for p in base}):
        by_sector[sec] = med_total([p for p in base if p.get("sector") == sec])
    by_h = {f"h{h}": med_total([p for p in base if p["h"] == h]) for h in (1, 2, 3)}
    pos = med_total([p for p in base if (p.get("fcff_a") or 0) > 0])
    neg = med_total([p for p in base if (p.get("fcff_a") or 0) <= 0])
    return {"global": med_total(base),
            "leave_one_out_rango": [min(loo_vals), max(loo_vals)] if loo_vals else None,
            "por_sector": by_sector, "por_horizonte": by_h,
            "fcff_real_positivo": pos, "fcff_real_negativo": neg,
            "nota": "valores = mediana del error FCFF escalado por ingresos (negativo ⇒ subestima)"}


def bias_audit(points: List[dict]) -> dict:
    out = {}
    for model in ("A", "D"):
        out[model] = {"descomposicion_global": bias_decomposition(points, model),
                      "descomposicion_por_horizonte": {f"h{h}": bias_decomposition(points, model, h) for h in (1, 2, 3)},
                      "reinversion": reinvestment_analysis(points, model),
                      "robustez": bias_robustness(points, model)}
    return out


def audit(points: List[dict]) -> dict:
    out = {"independencia": independence(points), "por_componente": {}, "fcff_acumulado": {},
           "comparaciones_emparejadas": {}}
    for model in ("A", "C", "D"):
        out["por_componente"][model] = {
            comp: {f"h{h}": component_metrics(points, model, comp, h) for h in (1, 2, 3)}
            for comp in COMPONENTS}
        out["fcff_acumulado"][model] = cumulative_fcff(points, model)
    for (m1, m2) in (("A", "D"), ("A", "C"), ("C", "D")):
        out["comparaciones_emparejadas"][f"{m1}_vs_{m2}"] = {
            comp: paired_cluster_bootstrap(points, m1, m2, comp) for comp in COMPONENTS}
    return out


def main(argv=None):
    import argparse
    import json
    import sys
    p = argparse.ArgumentParser()
    p.add_argument("--dump", required=True, help="JSON de puntos crudos de forecast_backtest")
    args = p.parse_args(argv)
    data = json.load(open(args.dump))
    pts = data.get("points", data) if isinstance(data, dict) else data
    print(json.dumps({"P1.8.1": "auditoría estadística", "n": len(pts), **audit(pts),
                      "P1.8.2_bias": bias_audit(pts)},
                     ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
