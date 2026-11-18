"""Pruebas de regresión de los hallazgos P0 de la auditoría de Codex (commit 5c4f6e3).

Cada test REPRODUCE el fallo anterior y verifica la corrección. No ajusta valores a mercado.
"""
from __future__ import annotations

from app.research.edgar_series import build_series_from_rows


def _row(concept, value, unit, period_end, period_start=None, filing="2026-02-20"):
    return {"concept": concept, "value": value, "unit": unit, "period_end": period_end,
            "period_start": period_start, "filing_date": filing, "taxonomy": "us-gaap"}


# ── F1: selección de unidad/moneda — no mezclar USD y TWD (caso TSM 20-F dual) ──────────────────────
def _tsm_dual_rows():
    # Revenue en TWD (fija ccy=TWD). Equity reportado en TWD y USD el MISMO periodo (20-F dual).
    return [
        _row("Revenues", 2_900_000_000_000, "TWD", "2024-12-31", "2024-01-01"),
        _row("StockholdersEquity", 4_279_271_600_000, "TWD", "2024-12-31"),
        _row("StockholdersEquity", 130_505_400_000, "USD", "2024-12-31"),
        _row("CashAndCashEquivalentsAtCarryingValue", 2_127_627_000_000, "TWD", "2024-12-31"),
        _row("LongTermDebt", 59_857_900_000, "TWD", "2024-12-31"),
    ]


def test_f1_unit_filter_rejects_foreign_currency():
    s = build_series_from_rows(_tsm_dual_rows())
    assert s["currency"] == "TWD"
    eq = list(s["by_field"]["equity"].values())[-1]
    assert eq == 4_279_271_600_000, f"equity debe ser TWD, no USD; obtuvo {eq}"


def test_f1_row_order_invariant():
    rows = _tsm_dual_rows()
    eq_fwd = list(build_series_from_rows(rows)["by_field"]["equity"].values())[-1]
    eq_rev = list(build_series_from_rows(list(reversed(rows)))["by_field"]["equity"].values())[-1]
    assert eq_fwd == eq_rev == 4_279_271_600_000, "el orden de filas no debe cambiar el equity seleccionado"


# ── F2: WACC internacional — capitalización homogénea en moneda local (ADR) ─────────────────────────
def test_f2_adr_market_cap_local_currency():
    from app.research.valuation_engine import normalize, Reconciled
    # Serie TWD mínima: ingresos, EBIT positivo, equity/deuda/caja, acciones ordinarias.
    by = {
        "revenue": {"2023-12-31": 2_100_000_000_000, "2024-12-31": 2_900_000_000_000},
        "operating_income": {"2023-12-31": 900_000_000_000, "2024-12-31": 1_200_000_000_000},
        "tax": {"2024-12-31": 180_000_000_000},
        "net_income": {"2024-12-31": 1_000_000_000_000},
        "equity": {"2024-12-31": 5_419_596_000_000},
        "total_debt": {"2024-12-31": 1_064_582_000_000},
        "cash": {"2024-12-31": 2_767_856_000_000},
        "shares": {"2024-12-31": 25_930_557_000},
        "ocf": {"2024-12-31": 1_500_000_000_000}, "capex": {"2024-12-31": -300_000_000_000},
    }
    rec = Reconciled(by_field=by, provenance={}, discrepancies={}, currency="TWD", notes=[])
    n = normalize("TSM", rec, price_local=405.49, adr=5)
    assert n.ok, n.fail
    # Con la capitalización en moneda local (precio ADR × ordinarias/ratio ÷ FX), el peso de equity supera
    # 0,97; el bug (precio_ADR × ordinarias) daría ~0,908.
    assert n.w_equity > 0.97, f"peso equity {n.w_equity} sugiere capitalización mal dimensionada (ADR)"


# ── F9: pérdida operativa no se convierte en rentabilidad +1% ───────────────────────────────────────
def test_f9_operating_loss_not_valued_positive():
    from app.research.valuation_engine import normalize, Reconciled
    by = {
        "revenue": {"2023-12-31": 100.0, "2024-12-31": 110.0},
        "operating_income": {"2023-12-31": -20.0, "2024-12-31": -15.0},  # pérdida operativa
        "equity": {"2024-12-31": 50.0}, "total_debt": {"2024-12-31": 10.0}, "cash": {"2024-12-31": 5.0},
        "shares": {"2024-12-31": 1_000_000}, "net_income": {"2024-12-31": -18.0},
    }
    rec = Reconciled(by_field=by, provenance={}, discrepancies={}, currency="USD", notes=[])
    n = normalize("LOSS", rec, price_local=10.0, adr=1)
    assert not n.ok and "margen" in (n.fail or ""), "una pérdida operativa no debe producir FV positivo"


# ── F7: TTM exige 4 trimestres contiguos ────────────────────────────────────────────────────────────
def test_f7_single_quarter_is_not_ttm():
    from app.research.ttm import ttm_by_quarters
    usg = {"NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
        {"start": "2026-01-01", "end": "2026-03-31", "val": 10.0, "form": "10-Q", "filed": "2026-04-30"},
    ]}}}
    res = ttm_by_quarters(usg, {}, {"10-K", "10-Q"})
    assert res["ttm"] == {}, "un solo trimestre no debe producir TTM"
    assert any(c[0] == "ttm_cuatro_trimestres_contiguos" and not c[1] for c in res["controles"])


# ── F3: insert_append cuenta inserciones REALES, no las enviadas ────────────────────────────────────
def test_f3_insert_append_counts_real_inserts():
    from app.jobs.supabase_writer import SupabaseWriter

    class _Resp:
        def __init__(self, body): self._b = body
        def raise_for_status(self): pass
        def json(self): return self._b

    class _Client:
        def post(self, *a, **k): return _Resp([{"id": 1}])  # se envían 2, solo 1 inserta (1 duplicado ignorado)

    w = SupabaseWriter.__new__(SupabaseWriter)
    w._client = _Client(); w.base = "http://x"
    n = w.insert_append("pit_snapshots", [{"a": 1}, {"a": 2}], on_conflict="k")
    assert n == 1, f"debe contar 1 insertada (no 2 enviadas); obtuvo {n}"
