"""Pruebas de la emisión prospectiva: idempotencia, seguridad (no fuga de secreto),
forma de las filas (origin/producción, horizontes, evaluate_on>as_of, etiqueta EXPERIMENTAL)
y una emisión oficial por (modelo,ticker,fecha,horizonte). Sin red."""
import random

import pytest

pytest.importorskip("sklearn")  # el entrenamiento usa Ridge; se omite si no está instalado

from app.jobs import emit_predictions as E


class FakeWriter:
    """Simula insert_append con resolution=ignore-duplicates sobre las columnas on_conflict."""
    def __init__(self):
        self.store = []           # filas "almacenadas"
        self._keys = set()

    def insert_append(self, table, rows, on_conflict):
        cols = on_conflict.split(",")
        for r in rows:
            k = tuple(r.get(c) for c in cols)
            if k in self._keys:
                continue          # duplicado -> DO NOTHING
            self._keys.add(k)
            self.store.append(r)
        return len(rows)

    def select_rows(self, table, select="*", page=1000, params=None):
        p = params or {}
        D = (p.get("as_of") or "").replace("eq.", "")
        return [{"model_name": r["model_name"], "model_version": r["model_version"],
                 "horizon_sessions": r["horizon_sessions"], "ticker": r["ticker"]}
                for r in self.store if (not D or r["as_of"] == D) and r["origin"] == "production"]


def _synthetic_data(seed=1, n_train=160, n_names=14):
    random.seed(seed)
    D = "2026-11-04"
    # mdates no se usa en emit(); train y pred sí.
    train = {h: [] for h in (20, 60, 252)}
    for h in (20, 60, 252):
        for _ in range(n_train):
            A = [random.gauss(0, 1) for _ in range(10)]
            B = [random.gauss(0, 1) for _ in range(7)]
            y = 0.3 * A[0] + 0.1 * B[0] + random.gauss(0, 0.05)
            train[h].append({"A": A, "B": B, "y": y})
    pred = {}
    for i in range(n_names):
        pred[f"TK{i}"] = {"A": [random.gauss(0, 1) for _ in range(10)],
                          "B": [random.gauss(0, 1) for _ in range(7)], "sector": "Tech"}
    return {"D": D, "mdates": [D], "train": train, "pred": pred}


def test_emit_shape_and_labels():
    w = FakeWriter()
    out = E.emit(_synthetic_data(), dry_run=False, writer=w, service_key="SECRET123")
    # A en 3 horizontes, B en 252
    hs = {(r["model_name"], r["horizon_sessions"]) for r in w.store}
    assert ("price-ridge", 20) in hs and ("price-ridge", 60) in hs and ("price-ridge", 252) in hs
    assert ("price-fund-ridge", 252) in hs
    assert not any(r["model_name"] == "price-fund-ridge" and r["horizon_sessions"] != 252 for r in w.store)
    for r in w.store:
        assert r["origin"] == "production"
        assert r["emitted_at"] and r["data_ref"]["status"] == "EXPERIMENTAL_NO_VALIDADO"
        assert r["evaluate_on"] > r["as_of"]           # calendario oficial, futuro
        assert r["run_id"] == f"{r['model_version']}:{r['as_of']}"
        assert r["calendar"] == "XNYS"
    assert out["stored_total"] == len(w.store)


def test_idempotent_reemission():
    w = FakeWriter()
    data = _synthetic_data()
    E.emit(data, dry_run=False, writer=w, service_key="x")
    n1 = len(w.store)
    E.emit(data, dry_run=False, writer=w, service_key="x")   # reemitir mismo día
    assert len(w.store) == n1                                # 0 nuevos -> idempotente


def test_one_official_per_slot():
    w = FakeWriter()
    data = _synthetic_data()
    E.emit(data, dry_run=False, writer=w, service_key="x")
    slots = [(r["model_name"], r["model_version"], r["ticker"], r["as_of"], r["horizon_sessions"])
             for r in w.store]
    assert len(slots) == len(set(slots))                     # una sola oficial por slot


def test_security_abort_on_secret_leak(monkeypatch):
    # inyecta el secreto en los datos de predicción -> debe abortar
    data = _synthetic_data()
    data["pred"]["TK0"]["sector"] = "LEAKED"
    orig = E._fit_predict

    def leaky(train_rows, names, feat, use_fund):
        res, a, b = orig(train_rows, names, feat, use_fund)
        if res:
            first = next(iter(res))
            res[first]["note"] = "TOPSECRETKEY"
        return res, a, b
    monkeypatch.setattr(E, "_fit_predict", leaky)
    with pytest.raises(RuntimeError, match="secret leak"):
        E.emit(data, dry_run=False, writer=FakeWriter(), service_key="TOPSECRETKEY")


def test_dry_run_writes_nothing():
    w = FakeWriter()
    out = E.emit(_synthetic_data(), dry_run=True, writer=w, service_key="x")
    assert out["dry_run"] and len(w.store) == 0 and out["total_rows"] > 0
