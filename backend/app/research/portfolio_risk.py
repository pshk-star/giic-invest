"""P2.0 — Motor de RIESGO DE PORTAFOLIO (puro, testeable, sin dependencias externas).

Entra: pesos, matriz de retornos ALINEADOS, metadatos (sector/país/moneda), look-through de ETF,
retornos de benchmark. Salen MÉTRICAS reproducibles. NO genera recomendaciones (eso será Advisor 3.0).
Metodología transparente: HHI de concentración, covarianza/correlación muestral, vol del portafolio,
contribución al riesgo por Euler, drawdown histórico, beta a benchmark, exposición cambiaria,
escenarios de estrés por shocks explícitos, e impacto marginal de añadir/reducir una posición.
"""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean
from typing import Dict, List, Optional, Tuple

PPY = 252  # periodos por año (diario) para anualizar volatilidad


# ------------------------- concentración -------------------------
def hhi(weights_by_group: Dict[str, float]) -> float:
    """Índice Herfindahl-Hirschman sobre pesos (0..1). Renormaliza por si no suman 1."""
    tot = sum(abs(w) for w in weights_by_group.values())
    if tot <= 0:
        return 0.0
    return sum((abs(w) / tot) ** 2 for w in weights_by_group.values())


def concentration(weights: Dict[str, float], meta: Dict[str, dict], key: str) -> dict:
    """Agrega pesos por grupo (sector/country/currency) y da HHI + top grupos. 'na' si falta."""
    by: Dict[str, float] = defaultdict(float)
    for t, w in weights.items():
        g = (meta.get(t, {}) or {}).get(key) or "na"
        by[g] += w
    top = sorted(by.items(), key=lambda kv: -abs(kv[1]))
    return {"hhi": round(hhi(dict(by)), 4), "n_grupos": len(by),
            "por_grupo": {g: round(w, 4) for g, w in top},
            "top": [{"grupo": g, "peso": round(w, 4)} for g, w in top[:5]]}


# ------------------------- solape económico acción↔ETF -------------------------
def economic_exposure(weights: Dict[str, float], etf_lookthrough: Dict[str, Dict[str, float]]) -> dict:
    """Exposición EFECTIVA por subyacente = peso directo + Σ(peso_ETF × peso_constituyente).
    Reporta exposición duplicada (nombres tenidos directa Y vía ETF)."""
    eff: Dict[str, float] = defaultdict(float)
    direct: Dict[str, float] = defaultdict(float)
    via_etf: Dict[str, float] = defaultdict(float)
    for t, w in weights.items():
        lt = etf_lookthrough.get(t)
        if lt:  # es un ETF: distribuye por look-through
            s = sum(lt.values()) or 1.0
            for h, hw in lt.items():
                add = w * (hw / s)
                eff[h] += add
                via_etf[h] += add
        else:
            eff[t] += w
            direct[t] += w
    dup = {t: {"directo": round(direct[t], 4), "via_etf": round(via_etf[t], 4),
               "efectivo": round(eff[t], 4)}
           for t in sorted(eff) if direct.get(t, 0) > 1e-9 and via_etf.get(t, 0) > 1e-9}
    return {"exposicion_efectiva": {t: round(v, 4) for t, v in sorted(eff.items(), key=lambda kv: -kv[1])},
            "duplicada": dup,
            "suma_duplicada": round(sum(min(direct[t], via_etf[t]) for t in dup), 4)}


# ------------------------- covarianza / correlación / vol -------------------------
def _cov(x: List[float], y: List[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mx, my = mean(x), mean(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (n - 1)


def cov_matrix(returns: Dict[str, List[float]]) -> Tuple[List[str], List[List[float]]]:
    tickers = list(returns.keys())
    M = [[_cov(returns[a], returns[b]) for b in tickers] for a in tickers]
    return tickers, M


def corr_from_cov(M: List[List[float]]) -> List[List[float]]:
    n = len(M)
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            d = math.sqrt(M[i][i] * M[j][j])
            out[i][j] = M[i][j] / d if d > 0 else 0.0
    return out


def annualized_vol(ret: List[float], ppy: int = PPY) -> float:
    if len(ret) < 2:
        return 0.0
    return math.sqrt(_cov(ret, ret)) * math.sqrt(ppy)


def portfolio_variance(weights: List[float], M: List[List[float]]) -> float:
    n = len(weights)
    return sum(weights[i] * weights[j] * M[i][j] for i in range(n) for j in range(n))


# ------------------------- contribución al riesgo (Euler) -------------------------
def risk_contributions(weights: Dict[str, float], returns: Dict[str, List[float]],
                       ppy: int = PPY) -> dict:
    """σ_p y contribución de cada posición por Euler: CR_i = w_i·(Σw)_i/σ_p; Σ CR_i = σ_p."""
    tickers = [t for t in weights if t in returns]
    w = [weights[t] for t in tickers]
    M = [[_cov(returns[a], returns[b]) for b in tickers] for a in tickers]
    var = portfolio_variance(w, M)
    sig = math.sqrt(var) if var > 0 else 0.0
    contrib = {}
    for i, t in enumerate(tickers):
        mcr = (sum(M[i][j] * w[j] for j in range(len(w))) / sig) if sig > 0 else 0.0  # marginal
        cr = w[i] * mcr                                                               # componente
        contrib[t] = {"peso": round(w[i], 4), "mcr": round(mcr * math.sqrt(ppy), 6),
                      "contrib": round(cr * math.sqrt(ppy), 6),
                      "contrib_pct": round(cr / sig, 4) if sig > 0 else 0.0}
    return {"vol_portafolio_anual": round(sig * math.sqrt(ppy), 4),
            "euler_check": round(sum(c["contrib"] for c in contrib.values()), 6),
            "por_posicion": dict(sorted(contrib.items(), key=lambda kv: -kv[1]["contrib_pct"]))}


# ------------------------- drawdown -------------------------
def max_drawdown(series: List[float]) -> dict:
    """Máximo drawdown sobre una serie de PRECIOS (o nivel acumulado). Devuelve profundidad y duración."""
    if len(series) < 2:
        return {"max_drawdown": 0.0}
    peak = series[0]; mdd = 0.0; peak_i = 0; trough_i = 0; best_peak_i = 0
    for i, x in enumerate(series):
        if x > peak:
            peak = x; peak_i = i
        dd = x / peak - 1.0 if peak > 0 else 0.0
        if dd < mdd:
            mdd = dd; trough_i = i; best_peak_i = peak_i
    return {"max_drawdown": round(mdd, 4), "pico_idx": best_peak_i, "valle_idx": trough_i,
            "duracion_periodos": trough_i - best_peak_i}


def portfolio_series(weights: Dict[str, float], returns: Dict[str, List[float]]) -> List[float]:
    """Nivel acumulado del portafolio (rebalanceo por-periodo a pesos fijos)."""
    tickers = [t for t in weights if t in returns]
    n = len(next(iter(returns.values()))) if returns else 0
    lvl = [1.0]
    for k in range(n):
        r = sum(weights[t] * returns[t][k] for t in tickers)
        lvl.append(lvl[-1] * (1 + r))
    return lvl


# ------------------------- beta a benchmark -------------------------
def beta(asset: List[float], bench: List[float]) -> Optional[float]:
    vb = _cov(bench, bench)
    return (_cov(asset, bench) / vb) if vb > 0 else None


def portfolio_beta(weights: Dict[str, float], returns: Dict[str, List[float]],
                   bench: List[float]) -> dict:
    tickers = [t for t in weights if t in returns]
    port = [sum(weights[t] * returns[t][k] for t in tickers) for k in range(len(bench))]
    b = beta(port, bench)
    te = annualized_vol([port[k] - bench[k] for k in range(len(bench))])  # tracking error
    return {"beta": round(b, 4) if b is not None else None, "tracking_error_anual": round(te, 4)}


# ------------------------- exposición cambiaria -------------------------
def fx_exposure(weights: Dict[str, float], meta: Dict[str, dict], base: str = "USD") -> dict:
    by: Dict[str, float] = defaultdict(float)
    for t, w in weights.items():
        ccy = (meta.get(t, {}) or {}).get("currency") or base
        by[ccy] += w
    non_base = round(sum(w for c, w in by.items() if c != base), 4)
    return {"por_moneda": {c: round(w, 4) for c, w in sorted(by.items(), key=lambda kv: -kv[1])},
            "base": base, "exposicion_no_base": non_base}


# ------------------------- estrés -------------------------
def stress(weights: Dict[str, float], returns: Dict[str, List[float]], meta: Dict[str, dict],
           scenarios: Dict[str, dict]) -> dict:
    """Escenarios por shocks EXPLÍCITOS. Un escenario mapea nombres o sectores a un retorno de shock;
    el impacto del portafolio = Σ peso·shock (shock del sector si no hay del nombre)."""
    out = {}
    for name, sc in scenarios.items():
        by_name = sc.get("by_ticker", {}) or {}
        by_sector = sc.get("by_sector", {}) or {}
        default = sc.get("default", 0.0)
        impact = 0.0
        for t, w in weights.items():
            if t in by_name:
                s = by_name[t]
            else:
                sec = (meta.get(t, {}) or {}).get("sector")
                s = by_sector.get(sec, default)
            impact += w * s
        out[name] = round(impact, 4)
    return out


# ------------------------- impacto marginal -------------------------
def marginal_impact(weights: Dict[str, float], returns: Dict[str, List[float]],
                    ticker: str, delta: float, meta: Dict[str, dict]) -> dict:
    """Impacto de añadir (+delta) o reducir (−delta) `ticker`, renormalizando. Δvol, Δconcentración."""
    base_rc = risk_contributions(weights, returns)
    new = dict(weights)
    new[ticker] = new.get(ticker, 0.0) + delta
    tot = sum(new.values())
    if tot > 0:
        new = {t: w / tot for t, w in new.items()}
    new_rc = risk_contributions(new, returns)
    base_c = concentration(weights, meta, "sector")["hhi"]
    new_c = concentration(new, meta, "sector")["hhi"]
    return {"ticker": ticker, "delta": delta,
            "vol_antes": base_rc["vol_portafolio_anual"], "vol_despues": new_rc["vol_portafolio_anual"],
            "delta_vol": round(new_rc["vol_portafolio_anual"] - base_rc["vol_portafolio_anual"], 4),
            "hhi_sector_antes": base_c, "hhi_sector_despues": round(new_c, 4),
            "pesos_despues": {t: round(w, 4) for t, w in new.items()}}
