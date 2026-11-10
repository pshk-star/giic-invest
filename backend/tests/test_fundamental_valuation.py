"""P1.9 — pruebas del payload de valoración fundamental (paridad, regresión, datos insuficientes)."""
from __future__ import annotations

from app.jobs.fundamental_valuation import evaluate, PRODUCTIVE_DCF


def test_giic_parity_reproduces_p16():
    # FCFF GIIC debe reproducir los FV del informe P1.6 (ancla de paridad, única lógica en backend)
    expect = {"NVDA": 145, "META": 670, "NFLX": 69, "TSM": 240, "ASML": 828}
    for t, fv in expect.items():
        out = evaluate(t, use_net=False)
        g = next(m for m in out["modelos"] if m["modelo"] == "FCFF_GIIC")
        assert abs(g["fair_value_usd"] - fv) <= 1.0, f"{t}: {g['fair_value_usd']} vs {fv}"


def test_productive_dcf_passthrough_not_recomputed():
    out = evaluate("NVDA", use_net=False)
    p = next(m for m in out["modelos"] if m["modelo"] == "DCF_productivo")
    assert p["fair_value_usd"] == PRODUCTIVE_DCF["NVDA"]      # passthrough de la tubería productiva
    assert p["confianza"] == "producción"                    # no experimental, no recálculo


def test_insufficient_data_models_marked_unavailable_offline():
    # sin red: corregido (tasas) y combinado (consenso) => disponible:false, NO recomendación
    out = evaluate("META", use_net=False)
    corr = next(m for m in out["modelos"] if m["modelo"] == "FCFF_corregido")
    comb = next(m for m in out["modelos"] if m["modelo"] == "FCFF_combinado_consenso")
    assert corr["disponible"] is False and corr.get("fair_value_usd") is None
    assert comb["disponible"] is False


def test_required_fields_present():
    out = evaluate("TSM", use_net=False)
    g = next(m for m in out["modelos"] if m["modelo"] == "FCFF_GIIC")
    for k in ("escenarios", "wacc_pct", "g_terminal_pct", "peso_terminal_pct",
              "reverse_dcf_g1_pct", "proyeccion_10a", "procedencia", "margen_seguridad_pct"):
        assert k in g, f"falta {k}"
    assert g["escenarios"]["conservador"] < g["escenarios"]["base"] < g["escenarios"]["optimista"]
    assert out["comparacion"]["explicacion"]


def test_confidence_from_evidence_not_automatic():
    # NVDA: error OOS alto (P1.8) + consenso por encima de guidance => NO alta
    out = evaluate("NVDA", use_net=False)
    g = next(m for m in out["modelos"] if m["modelo"] == "FCFF_GIIC")
    assert g["confianza"] in ("baja", "media")
