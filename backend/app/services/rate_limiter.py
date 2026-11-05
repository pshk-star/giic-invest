"""Limitador de tasa (token bucket) y utilidades de procesamiento por lotes.

El token bucket controla el consumo de la API del proveedor (p.ej. EODHD limita
req/min o req/día). El reloj es inyectable para poder probar el comportamiento sin
esperar en tiempo real. `batched` divide un universo grande en lotes para procesarlo
de forma incremental sin disparar los límites.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, List, TypeVar

T = TypeVar("T")


@dataclass
class TokenBucket:
    """Permite `rate` tokens por `per` segundos, con capacidad de ráfaga `capacity`.

    `acquire(n)` devuelve el tiempo (segundos) que habría que esperar para disponer
    de n tokens. En producción se combina con `sleep`; en pruebas se inspecciona el
    retardo devuelto sin dormir.
    """
    rate: float                      # tokens por ventana
    per: float = 60.0                # tamaño de la ventana en segundos
    capacity: float = 0.0            # ráfaga máxima (0 => igual a rate)
    clock: Callable[[], float] = time.monotonic
    _tokens: float = field(default=0.0, init=False)
    _last: float = field(default=0.0, init=False)

    def __post_init__(self):
        if self.capacity <= 0:
            self.capacity = self.rate
        self._tokens = self.capacity
        self._last = self.clock()

    def _refill(self):
        now = self.clock()
        elapsed = now - self._last
        self._last = now
        self._tokens = min(self.capacity, self._tokens + elapsed * (self.rate / self.per))

    def acquire(self, n: float = 1.0) -> float:
        """Reserva n tokens. Devuelve segundos a esperar (0 si hay disponibilidad)."""
        self._refill()
        if self._tokens >= n:
            self._tokens -= n
            return 0.0
        deficit = n - self._tokens
        wait = deficit * (self.per / self.rate)
        self._tokens = 0.0
        return wait

    def tokens(self) -> float:
        self._refill()
        return self._tokens


def batched(items: Iterable[T], size: int) -> Iterator[List[T]]:
    """Divide un iterable en lotes de tamaño `size` (el último puede ser menor)."""
    if size <= 0:
        raise ValueError("size debe ser > 0")
    batch: List[T] = []
    for it in items:
        batch.append(it)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def throttle(bucket: TokenBucket, n: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> float:
    """Espera lo necesario para respetar el límite y consume n tokens. Devuelve la espera."""
    wait = bucket.acquire(n)
    if wait > 0:
        sleep(wait)
    return wait
