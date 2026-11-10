"""P1.7.2 — pruebas del motor FCFF experimental (paridad con P1.6 + identidades + atribución)."""
from __future__ import annotations

import pytest

from app.research.fcff_forward import (Assump, Base, value_p16, value_path, project_path,
                                       p16_path, attribute_fv)
from app.research.fcff_forward_report import BASE, ASSUMP


def test_p16_parity_reproduces_report_fv():
    # El motor forward con senda mecánica reproduce los FV del informe P1.6 (ancla de benchmark).
    expect = {"NVDA": 145, "META": 670, "NFLX": 69, "TSM": 240, "ASML": 828}
    for t, fv in expect.items():
        got = value_p16(BASE[t], ASSUMP[t])["bridge"]["ps_usd"]
        assert abs(got - fv) <= 1.0, f"{t}: {got} vs {fv}"


def test_fcff_identity_and_ev_decomposition():
    b = Base("X", "USD", 1000.0, 0.30, -100.0, 10.0)
    a = Assump(1.2, 0.05, 0.1, 0.15, 2.0, 0.10, 0.30, 0.20)
    g, m = p16_path(a.g1, 0.041, b.ebit_margin0, a.margin_terminal, a.years)
    proj = project_path(b, a, g, m, 0.041, a.margin_terminal, 0.09)
    for r in proj["rows"]:
        assert abs(r["fcff"] - (r["nopat"] - r["reinvest"])) < 1e-6
    assert abs(proj["ev"] - (proj["pv_fcff"] + proj["pv_tv"])) < 1e-6
    assert 0 < proj["terminal_weight"] < 1


def test_reinvest_terminal_consistent():
    b, a = BASE["TSM"], ASSUMP["TSM"]
    v = value_p16(b, a)
    assert abs(v["proj"]["reinvest_terminal"] - v["gT"] / a.roic_terminal) < 1e-9


def test_wacc_must_exceed_gt():
    b = Base("X", "USD", 1000.0, 0.30, 0.0, 10.0)
    a = Assump(1.2, 0.05, 0.1, 0.15, 2.0, 0.10, 0.30, 0.20)
    g, m = p16_path(0.10, 0.041, 0.30, 0.30, 10)
    with pytest.raises(ValueError):
        project_path(b, a, g, m, 0.02, 0.30, 0.02)   # wacc<=gT


def test_path_length_validation():
    b, a = BASE["NVDA"], ASSUMP["NVDA"]
    with pytest.raises(ValueError):
        project_path(b, a, [0.1] * 5, [0.3] * 5, 0.041, 0.45, 0.10)  # longitud != years


def test_attribution_sums_to_total():
    b, a = BASE["META"], ASSUMP["META"]
    # senda nueva arbitraria pero válida
    g_new = [0.20, 0.18] + [0.041 + (0.18 - 0.041) * (1 - (i - 2) / 8) for i in range(3, 11)]
    m_new = [0.42, 0.41] + [0.38] * 8
    attr = attribute_fv(b, a, g_new, m_new, gT_new=0.041)
    s = (attr["contrib_growth"] + attr["contrib_margin"] + attr["contrib_reinvest"]
         + attr["contrib_wacc_terminal"])
    assert abs(s - attr["delta_total"]) < 0.05
    assert abs((attr["fv_new"] - attr["fv_p16"]) - attr["delta_total"]) < 0.02


def test_adr_and_fx_applied():
    # TSM: ADR=5, FX TWD; ASML: ADR=1, FX EUR
    assert BASE["TSM"].adr == 5 and BASE["ASML"].adr == 1
    vt = value_p16(BASE["TSM"], ASSUMP["TSM"])
    # ps_usd = ps_local * FX_TWD * 5
    assert abs(vt["bridge"]["ps_usd"] - vt["bridge"]["ps_local"] * (1 / 32.80) * 5) < 1e-6
