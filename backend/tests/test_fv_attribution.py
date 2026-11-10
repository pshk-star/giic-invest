"""P1.7.4 — pruebas de atribución y control del impacto del consenso (puras)."""
from __future__ import annotations

from app.research.fcff_forward import Assump, Base
import app.research.fv_attribution as fa


def _b():
    return Base("X", "USD", 200e9, 0.60, 0.0, 10e9, tax_rate=0.15, interest=0.0)


def _a():
    return Assump(1.3, 0.05, 0.03, 0.15, 2.5, 0.30, 0.45, 0.22)


def test_override_front_isolates_years():
    gi = fa.giic_growths(_a(), 0.041)
    g = fa.override_front(gi, [0.90, 0.68], 1)
    assert g[0] == 0.90 and g[1] == gi[1] and g[2] == gi[2]   # solo año 1 cambia
    g2 = fa.override_front(gi, [0.90, 0.68], 2)
    assert g2[0] == 0.90 and g2[1] == 0.68 and g2[2] == gi[2]


def test_transition_meanrev_halves_excess():
    tail = fa.transition_tail(0.68, 0.04, k=2, years=10, mode="meanrev")
    # año 3 (t=1): 0.04 + 0.64*0.5 = 0.36 ; año 4 (t=2): 0.04+0.64*0.25=0.20
    assert abs(tail[0] - 0.36) < 1e-9 and abs(tail[1] - 0.20) < 1e-9
    assert tail[-1] < 0.05   # converge a gT


def test_transition_linear_vs_meanrev_meanrev_lower_tail():
    lin = fa.transition_tail(0.68, 0.04, 2, 10, "linear")
    mr = fa.transition_tail(0.68, 0.04, 2, 10, "meanrev")
    # la reversión deja crecimiento menor en los años intermedios (3-5)
    assert mr[0] < lin[0] and mr[1] < lin[1] and mr[2] < lin[2]


def test_pv_decomposition_sums_to_ev():
    b, a = _b(), _a()
    g = fa.consensus_growths([0.90, 0.68], a, 0.041, "meanrev")
    m = fa.giic_margins(b, a)
    from app.research.fcff_forward import wacc_of
    w = wacc_of(a, "USD")["wacc"]
    dec = fa.pv_decomposition(b, a, g, m, 0.041, w)
    assert abs((dec["pv_1_3"] + dec["pv_4_10"] + dec["pv_terminal"]) - dec["ev"]) < 1.0


def test_mechanism_meanrev_cuts_tail_not_near_term():
    """El hallazgo central: la reversión recorta años 4-10 + terminal, NO los años 1-3."""
    b, a = _b(), _a()
    ee = [None, None]
    gl = fa.consensus_growths([0.90, 0.68], a, 0.041, "linear")
    gm = fa.consensus_growths([0.90, 0.68], a, 0.041, "meanrev")
    ml = fa.giic_margins(b, a)
    vl = fa.value(b, a, gl, ml, 0.041)
    vm = fa.value(b, a, gm, ml, 0.041)
    # años 1-3 casi iguales; el gran recorte está en 4-10 y terminal
    assert abs(vl["pv_1_3"] - vm["pv_1_3"]) / vl["pv_1_3"] < 0.05
    assert vm["pv_4_10"] < vl["pv_4_10"] * 0.7
    assert vm["pv_terminal"] < vl["pv_terminal"] * 0.6
    assert vm["ps_usd"] < vl["ps_usd"]   # FV corregido menor, sin tope arbitrario


def test_attribution_steps_present_and_ordered():
    at = fa.attribution(_b(), _a(), 0.041, [0.90, 0.68], [None, None], mode="meanrev")
    names = [s["paso"] for s in at["pasos"]]
    assert names == ["A_GIIC", "B_consenso_año1", "C_consenso_plurianual", "D_mas_margenes", "E_combinado"]
    assert at["pasos"][0]["delta_abs"] == 0.0   # A es la base
    assert at["K_años_explicitos"] == 2


def test_reconciled_margins_coherent_band():
    b, a = _b(), _a()
    g = fa.consensus_growths([0.90, 0.68], a, 0.041, "meanrev")
    # EPS plausible => margen dentro de banda; EPS absurdo => cae a m0
    m_ok, f_ok = fa.reconciled_margins(b, a, [20.0, 25.0], g, 2)
    m_bad, f_bad = fa.reconciled_margins(b, a, [500.0, 600.0], g, 2)
    assert m_bad[0] == b.ebit_margin0   # incoherente => m0
