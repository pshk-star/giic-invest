"""P1.9 — verificaciones previas a la integración (pedidas por Pablo)."""
from __future__ import annotations

from statistics import median

from app.research.forecast_models import project
from app.research.forecast_audit import decompose_point


def _series(growth, margin, capex_pct, dna_pct, wc_pct=0.0, n=12, rev0=1000.0):
    s, rev = [], rev0
    for i in range(n):
        s.append({"year": f"{2010+i}-12-31", "revenue": rev, "ebit": rev * margin,
                  "ebit_margin": margin, "pretax": rev * margin, "tax": rev * margin * 0.15,
                  "capex": -(rev * capex_pct), "dna": rev * dna_pct, "wc_change": rev * wc_pct})
        rev *= (1 + growth)
    return s


# --- Verificación 1: reconciliación EXACTA por observación (no por medianas) ---
def test_reconciliation_exact_every_observation():
    import random
    random.seed(7)
    pts = []
    for _ in range(300):
        rev_a = random.uniform(50, 500); rev_f = rev_a * random.uniform(0.8, 1.3)
        m_a = random.uniform(0.1, 0.5); m_f = random.uniform(0.1, 0.5)
        t_a = random.uniform(0.1, 0.3); t_f = random.uniform(0.1, 0.3)
        R_a = random.uniform(-20, 60); R_f = random.uniform(-20, 60)
        ebit_a = rev_a * m_a; ebit_f = rev_f * m_f
        fcff_a = ebit_a * (1 - t_a) - R_a; fcff_f = ebit_f * (1 - t_f) - R_f
        pts.append({"rev_f": rev_f, "rev_a": rev_a, "margin_f": m_f, "margin_a": m_a,
                    "ebit_f": ebit_f, "ebit_a": ebit_a, "reinv_f": R_f, "reinv_a": R_a,
                    "fcff_f": fcff_f, "fcff_a": fcff_a})
    worst = 0.0
    for p in pts:
        d = decompose_point(p)
        recon = d["rev"] + d["margin"] + d["tax"] + d["reinv"] + d["interaction"]
        worst = max(worst, abs(recon - d["total"]))
    assert worst < 1e-9          # EXACTA en CADA observación


def test_component_medians_need_not_sum_to_total_median():
    # demostración explícita: medianas de componentes != mediana del total (no es un error)
    import random
    random.seed(1)
    decs = []
    for _ in range(200):
        rev_a = 100.0; rev_f = rev_a * random.uniform(0.9, 1.2)
        m_a = 0.3; m_f = random.choice([0.2, 0.4])
        pt = {"rev_f": rev_f, "rev_a": rev_a, "margin_f": m_f, "margin_a": m_a,
              "ebit_f": rev_f * m_f, "ebit_a": rev_a * m_a, "reinv_f": 5, "reinv_a": 5,
              "fcff_f": rev_f * m_f * 0.85 - 5, "fcff_a": rev_a * m_a * 0.85 - 5}
        decs.append(decompose_point(pt))
    sum_of_medians = sum(median([d[k] for d in decs]) for k in ("rev", "margin", "tax", "reinv", "interaction"))
    median_of_total = median([d["total"] for d in decs])
    assert abs(sum_of_medians - median_of_total) > 1e-6   # difieren: por eso se reporta por observación


# --- Verificación 2: la corrección NO impone reinversión neta baja en intensivas en capital ---
def test_corrected_reinvestment_high_for_capital_intensive():
    # capex 40% ingresos, D&A 15% => reinversión neta ~25% de ingresos (alta, correcta)
    s = _series(0.10, 0.45, capex_pct=0.40, dna_pct=0.15, wc_pct=0.01)
    p = project("A", s, 8, 0.04, (1, 2, 3))
    rc = p[1]["reinvest_corr"]; rev1 = p[1]["revenue"]
    assert rc / rev1 > 0.20          # sigue siendo intensiva en capital, no se aplana


def test_corrected_reinvestment_preserves_negative():
    # capex 5% < D&A 9% => reinversión neta NEGATIVA (desinversión) — se conserva, no se pisa a 0
    s = _series(0.05, 0.30, capex_pct=0.05, dna_pct=0.09, wc_pct=0.0)
    p = project("A", s, 8, 0.04, (1, 2, 3))
    assert p[1]["reinvest_corr"] < 0


def test_corrected_reinvestment_tracks_expansion():
    # capex alto creciente (expansión) => reinversión corregida alta (no artificialmente baja)
    s = _series(0.15, 0.40, capex_pct=0.35, dna_pct=0.12, wc_pct=0.02)
    p = project("A", s, 8, 0.04, (1, 2, 3))
    assert p[1]["reinvest_corr"] > 0 and p[1]["reinvest_corr"] / p[1]["revenue"] > 0.18
