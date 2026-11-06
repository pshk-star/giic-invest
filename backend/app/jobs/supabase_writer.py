"""Escritura de resultados a Supabase vía su API REST (PostgREST).

Usa la SERVICE ROLE KEY (solo en GitHub Actions Secrets, nunca en el navegador ni
en el repo). `build_snapshot_rows` es puro y se prueba; el envío HTTP corre en el job.
Cada snapshot guarda metadatos POINT-IN-TIME (fecha de cálculo, versión de universo
y de algoritmo, cobertura, valores de factores) para habilitar backtesting sin
look-ahead en una fase futura.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Mapping, Optional


def build_snapshot_rows(scan_result: dict, run_id: str, as_of: str,
                        universe_version: str, algo_version: str) -> List[dict]:
    """Convierte el ranking del scanner en filas para la tabla scan_snapshots."""
    rows = []
    for r in scan_result.get("ranking", []):
        rows.append({
            "run_id": run_id,
            "as_of": as_of,
            "universe_version": universe_version,
            "algo_version": algo_version,
            "ticker": r["ticker"],
            "rank": r["rank"],
            "composite": r["composite"],
            "factor_value": r["factors"].get("value"),
            "factor_quality": r["factors"].get("quality"),
            "factor_growth": r["factors"].get("growth"),
            "factor_momentum": r["factors"].get("momentum"),
            "factor_low_risk": r["factors"].get("low_risk"),
            "tags": r.get("tags", []),
            "sector": r.get("sector"),
            "is_sample": r.get("is_sample", False),
        })
    return rows


def build_run_row(run_id: str, as_of: str, scan_result: dict,
                  universe_version: str, algo_version: str) -> dict:
    """Fila de metadatos de la corrida. Nace en estado 'pending'; el frontend solo
    consulta corridas 'completed' (publicación atómica)."""
    return {
        "id": run_id,
        "as_of": as_of,
        "created_at": datetime.utcnow().isoformat(),
        "status": "pending",
        "universe_version": universe_version,
        "algo_version": algo_version,
        "evaluated": scan_result.get("evaluated", 0),
        "using_sample_data": scan_result.get("using_sample_data", False),
        "coverage": scan_result.get("coverage", {}),
        "usable_factors": scan_result.get("usable_factors", []),
        "excluded_insufficient_data": scan_result.get("excluded_insufficient_data", []),
        "stale_excluded": scan_result.get("stale_excluded", []),
        "fresh_fraction": scan_result.get("fresh_fraction"),
        "weights": scan_result.get("weights", {}),
    }


class SupabaseWriter:
    def __init__(self, url: str, service_role_key: str, timeout: float = 30.0):
        if not url or not service_role_key:
            raise ValueError("SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY son obligatorios.")
        import httpx
        self.base = url.rstrip("/") + "/rest/v1"
        self._client = httpx.Client(timeout=timeout, headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        })

    def upsert(self, table: str, rows: List[dict], on_conflict: Optional[str] = None) -> int:
        if not rows:
            return 0
        headers = {"Prefer": "resolution=merge-duplicates,return=minimal"}
        params = {"on_conflict": on_conflict} if on_conflict else {}
        r = self._client.post(f"{self.base}/{table}", json=rows, params=params, headers=headers)
        r.raise_for_status()
        return len(rows)

    def insert(self, table: str, row: dict) -> None:
        r = self._client.post(f"{self.base}/{table}", json=row,
                              headers={"Prefer": "return=minimal"})
        r.raise_for_status()

    def insert_append(self, table: str, rows: List[dict], on_conflict: str) -> int:
        """Inserta ignorando duplicados (NO hace UPDATE). Para tablas APPEND-ONLY cuyos
        triggers rechazan UPDATE: on conflict se omite la fila, no se actualiza."""
        if not rows:
            return 0
        headers = {"Prefer": "resolution=ignore-duplicates,return=minimal"}
        r = self._client.post(f"{self.base}/{table}", json=rows,
                              params={"on_conflict": on_conflict}, headers=headers)
        r.raise_for_status()
        return len(rows)

    def select_rows(self, table: str, select: str = "*", page: int = 1000,
                    params: Optional[dict] = None) -> List[dict]:
        """Lee filas paginando (service role). Requiere columna 'id' para ordenar."""
        out: List[dict] = []
        offset = 0
        while True:
            p = {"select": select, "limit": str(page), "offset": str(offset), "order": "id"}
            if params:
                p.update(params)
            r = self._client.get(f"{self.base}/{table}", params=p)
            r.raise_for_status()
            batch = r.json()
            out.extend(batch)
            if len(batch) < page:
                break
            offset += page
        return out

    def get_transaction_tickers(self) -> List[str]:
        """Tickers distintos presentes en transactions (service_role omite RLS).
        Solo se leen tickers (no montos ni usuarios): sirve para precios/identificación."""
        try:
            r = self._client.get(f"{self.base}/transactions", params={"select": "ticker"})
            r.raise_for_status()
            return sorted({row["ticker"].upper() for row in r.json() if row.get("ticker")})
        except Exception:
            return []

    def update_run_status(self, run_id: str, status: str, error: Optional[str] = None) -> None:
        """Marca una corrida como 'completed' o 'failed' (publicación atómica)."""
        payload = {"status": status}
        if status == "completed":
            payload["completed_at"] = datetime.utcnow().isoformat()
        if error:
            payload["error"] = error[:500]
        r = self._client.patch(f"{self.base}/scan_runs", json=payload,
                               params={"id": f"eq.{run_id}"},
                               headers={"Prefer": "return=minimal"})
        r.raise_for_status()
