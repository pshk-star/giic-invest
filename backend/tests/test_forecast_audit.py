"""P1.8.1 — pruebas de la auditoría estadística (puras)."""
from __future__ import annotations

from app.research.forecast_audit import (_abs_error, _signed_error, independence,
                                         component_metrics, cumulative_fcff,
                                         paired_cluster_bootstrap)


def _pt(tk, by, h, model, rev_f, rev_a, fcff_f, fcff_a, margin_f=0.3, margin_a=0.3):
    return {"ticker": tk, "base_year": by, "h": h, "model": model, "rev_a": rev_a,
            "rev_f": rev_f, "margin_f": margin_f, "margin_a": margin_a,
            "fcff_f": fcff_f, "fcff_a": fcff_a}


def test_abs_error_scales():
    p = _pt("X", "2020", 1, "A", 110, 100, 12, 10, 0.31, 0.30)
    assert abs(_abs_error(p, "rev") - 0.10) < 1e-9       # relativo
    assert abs(_abs_error(p, "margin") - 0.01) < 1e-9        # pp
    assert abs(_abs_error(p, "fcff") - 0.02) < 1e-9          # (12-10)/100 escalado por ingresos


def test_fcff_near_zero_diagnostic_not_deleted():
    # FCFF real casi cero => error relativo clásico enorme, pero escalado por ingresos pequeño
    pts = [_pt("X", "2020", 1, "A", 110, 100, 3, 1, ),      # fcff_a=1 (1% de ingresos): casi cero
           _pt("Y", "2020", 1, "A", 210, 200, 22, 20)]      # fcff_a=20 (10%): normal
    m = component_metrics(pts, "A", "fcff", 1)
    assert m["frac_fcff_casi_cero"] == 0.5                  # no borra: los cuenta
    assert m["rel_error_clasico"] >= m["rel_error_sin_denominador_casi_cero"]  # el clásico infla
    assert m["mae"] is not None                              # escalado por ingresos sigue acotado


def test_component_metrics_revenue():
    pts = [_pt("X", "2020", 1, "A", 110, 100, 10, 10), _pt("X", "2021", 1, "A", 95, 100, 10, 10)]
    m = component_metrics(pts, "A", "rev", 1)
    assert m["n"] == 2 and m["mae"] == 0.075 and m["wape"] is not None


def test_cumulative_fcff_needs_all_three_horizons():
    pts = []
    for h in (1, 2, 3):
        pts.append(_pt("X", "2020", h, "A", 100, 100, 10 + h, 9 + h))
    c = cumulative_fcff(pts, "A")
    assert c["n"] == 1 and c["mae_escalado_ingresos"] is not None
    # sin h=3 => no computa esa unidad
    c2 = cumulative_fcff([p for p in pts if p["h"] != 3], "A")
    assert c2["n"] == 0


def test_paired_cluster_bootstrap_detects_difference():
    # A siempre mejor que D en fcff (error menor) en 4 empresas => diferencia significativa
    pts = []
    for co in ("A1", "A2", "A3", "A4"):
        for by in ("2018", "2019", "2020"):
            pts.append(_pt(co, by, 1, "A", 100, 100, 10.5, 10))   # |err| fcff = 0.5/100
            pts.append(_pt(co, by, 1, "D", 100, 100, 13.0, 10))   # |err| fcff = 3.0/100
    r = paired_cluster_bootstrap(pts, "A", "D", "fcff", nb=500)
    assert r["significativo"] is True and r["mejor"] == "A"


def test_paired_insufficient_flagged():
    pts = [_pt("X", "2020", 1, "A", 100, 100, 10, 10), _pt("X", "2020", 1, "D", 100, 100, 11, 10)]
    r = paired_cluster_bootstrap(pts, "A", "D", "fcff")
    assert r.get("insuficiente") is True


def test_independence_counts():
    pts = [_pt("X", "2020", h, "A", 100, 100, 10, 10) for h in (1, 2, 3)]
    pts += [_pt("X", "2021", h, "A", 100, 100, 10, 10) for h in (1, 2, 3)]
    ind = independence(pts)
    assert ind["total_obs"] == 6 and ind["empresas"] == 1 and ind["unidades_empresa_x_año_base"] == 2
