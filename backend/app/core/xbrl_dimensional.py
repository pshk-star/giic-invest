"""E3.2 — extractor XBRL DIMENSIONAL reutilizable (puro; sin red ni pandas).

Parsea el XBRL inline de una presentación (p. ej. 10-K) y recupera hechos CON sus dimensiones
(clases accionarias, segmentos), conservando dimensión, clase, período (cierre), unidad y escala.
Universal: itera los hechos `ix:nonFraction` y sus contextos; NO contiene lógica por empresa.

Regla clave (E3.2): NO combina clases ni fabrica un EPS consolidado. Devuelve los valores POR CLASE
con su etiqueta. La selección de una clase para valoración es responsabilidad de capas superiores.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

_CTX = re.compile(r'<(?:\w+:)?context\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</(?:\w+:)?context>', re.I | re.S)
_MEMBER = re.compile(r'<(?:\w+:)?explicitmember\b[^>]*\bdimension="([^"]+)"[^>]*>\s*([^<\s]+)\s*</(?:\w+:)?explicitmember>', re.I | re.S)
_START = re.compile(r'<(?:\w+:)?startdate>\s*([0-9-]+)\s*</', re.I)
_END = re.compile(r'<(?:\w+:)?enddate>\s*([0-9-]+)\s*</', re.I)
_INSTANT = re.compile(r'<(?:\w+:)?instant>\s*([0-9-]+)\s*</', re.I)
_FACT = re.compile(r'<ix:nonfraction\b([^>]*)>(.*?)</ix:nonfraction>', re.I | re.S)
_UNIT = re.compile(r'<(?:\w+:)?unit\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</(?:\w+:)?unit>', re.I | re.S)
_MEASURE = re.compile(r'<(?:\w+:)?measure>\s*([^<\s]+)\s*</', re.I)
_TAGS = re.compile(r'<[^>]+>')


def _attr(attrs: str, name: str) -> Optional[str]:
    m = re.search(r'\b' + name + r'="([^"]*)"', attrs, re.I)
    return m.group(1) if m else None


def _pd(s: Optional[str]) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _num(text: Optional[str], scale: Optional[str], sign: Optional[str]) -> Optional[float]:
    """Valor numérico aplicando escala (×10^scale) y signo del XBRL inline."""
    t = re.sub(r'[,\s ]', '', _TAGS.sub('', text or ''))
    if t in ('', '-', '—'):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    try:
        v *= 10 ** int(scale) if scale not in (None, '') else 1
    except ValueError:
        pass
    if sign == '-':
        v = -v
    return v


def _short(qname: Optional[str]) -> Optional[str]:
    """Nombre corto de un QName ('vis:ClassAMember' -> 'ClassAMember'; 'us-gaap:X' -> 'X')."""
    if not qname:
        return None
    return qname.split(':', 1)[1] if ':' in qname else qname


def _units(html: str) -> Dict[str, str]:
    """Mapa unitRef → unidad legible (USD, shares, USD/shares, EUR, …)."""
    out = {}
    for uid, body in _UNIT.findall(html):
        meas = [_short(m) for m in _MEASURE.findall(body)]
        is_ratio = bool(re.search(r'<(?:\w+:)?divide', body, re.I)
                        or re.search(r'<(?:\w+:)?unitdenominator', body, re.I))
        if is_ratio:
            num = next((m for m in meas if m and (m.upper() in ("USD", "EUR", "GBP", "TWD", "JPY") or len(m) == 3)),
                       meas[0] if meas else None)
            den = next((m for m in meas if m and "shares" in m.lower()), None)
            out[uid] = f"{(num or '').upper()}/{'shares' if den else (meas[1] if len(meas) > 1 else '?')}"
        elif meas:
            m0 = meas[0]
            out[uid] = "shares" if "shares" in (m0 or "").lower() else (m0.upper() if m0 else uid)
        else:
            out[uid] = uid
    return out


@dataclass
class DimFact:
    concept: str                       # nombre corto us-gaap (EarningsPerShareDiluted)
    value: Optional[float]
    unit: Optional[str]                # USD/shares, shares, USD…
    period_start: Optional[date]
    period_end: Optional[date]
    is_duration: bool
    dimensions: Dict[str, str] = field(default_factory=dict)   # {axis_corto: member_corto}
    context_id: str = ""

    @property
    def is_dimensional(self) -> bool:
        return bool(self.dimensions)

    @property
    def share_class(self) -> Optional[str]:
        """Clase accionaria si el hecho está dimensionado por StatementClassOfStockAxis."""
        for axis, member in self.dimensions.items():
            if "classofstock" in axis.lower() or "statementclass" in axis.lower():
                return member
        return None

    def as_dict(self) -> dict:
        return {"concept": self.concept, "value": self.value, "unit": self.unit,
                "period_start": self.period_start.isoformat() if self.period_start else None,
                "period_end": self.period_end.isoformat() if self.period_end else None,
                "is_duration": self.is_duration, "dimensions": self.dimensions,
                "share_class": self.share_class, "context_id": self.context_id}


def _parse_contexts(html: str) -> Dict[str, dict]:
    ctx = {}
    for cid, body in _CTX.findall(html):
        dims = {}
        for axis, member in _MEMBER.findall(body):
            dims[_short(axis)] = _short(member)
        s, e, inst = _START.search(body), _END.search(body), _INSTANT.search(body)
        if inst:
            ctx[cid] = {"start": None, "end": _pd(inst.group(1)), "duration": False, "dims": dims}
        else:
            ctx[cid] = {"start": _pd(s.group(1)) if s else None,
                        "end": _pd(e.group(1)) if e else None, "duration": True, "dims": dims}
    return ctx


def extract_dimensional_facts(html: str, concepts: List[str], taxonomy: str = "us-gaap") -> List[DimFact]:
    """Extrae hechos de los `concepts` (nombres cortos, p. ej. EarningsPerShareDiluted) del XBRL
    inline, con dimensiones/clase/período/unidad. No combina clases ni consolida."""
    ctx = _parse_contexts(html)
    units = _units(html)
    want = {c.lower() for c in concepts}
    pref = taxonomy.lower() + ":"
    out: List[DimFact] = []
    for attrs, inner in _FACT.findall(html):
        name = (_attr(attrs, "name") or "").strip()
        short = _short(name)
        if not short or short.lower() not in want:
            continue
        if pref and name.lower().startswith(("us-gaap:", "ifrs-full:")) and not name.lower().startswith(pref):
            continue
        cref = _attr(attrs, "contextRef")
        c = ctx.get(cref, {})
        out.append(DimFact(
            concept=short,
            value=_num(inner, _attr(attrs, "scale"), _attr(attrs, "sign")),
            unit=units.get(_attr(attrs, "unitRef"), _attr(attrs, "unitRef")),
            period_start=c.get("start"), period_end=c.get("end"),
            is_duration=c.get("duration", True), dimensions=c.get("dims", {}) or {},
            context_id=cref or "",
        ))
    return out


def latest_annual_by_class(facts: List[DimFact], concept: str) -> Dict[str, DimFact]:
    """Para un concepto, el hecho ANUAL (duración ~365d) más reciente POR CLASE accionaria. Mantiene
    las clases SEPARADAS (no las combina). Clave = clase ('ClassAMember') o '__sin_clase__'."""
    best: Dict[str, DimFact] = {}
    for f in facts:
        if f.concept != concept or not f.is_duration or f.value is None:
            continue
        if not (f.period_start and f.period_end):
            continue
        if not (330 <= (f.period_end - f.period_start).days <= 400):
            continue
        key = f.share_class or "__sin_clase__"
        cur = best.get(key)
        if cur is None or (f.period_end > cur.period_end):
            best[key] = f
    return best
