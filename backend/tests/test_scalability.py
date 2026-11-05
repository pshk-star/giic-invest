"""Pruebas de escalabilidad: token bucket, batching y lógica de caché (pura)."""
from datetime import date, datetime, timedelta

from app.services import cache
from app.services.rate_limiter import TokenBucket, batched


class FakeClock:
    def __init__(self):
        self.t = 0.0
    def __call__(self):
        return self.t
    def advance(self, s):
        self.t += s


def test_token_bucket_allows_burst_then_throttles():
    clk = FakeClock()
    b = TokenBucket(rate=60, per=60.0, capacity=5, clock=clk)  # 1 token/seg, ráfaga 5
    assert b.acquire(5) == 0.0          # consume la ráfaga
    wait = b.acquire(1)                  # sin tokens => debe esperar ~1s
    assert abs(wait - 1.0) < 1e-6


def test_token_bucket_refills_over_time():
    clk = FakeClock()
    b = TokenBucket(rate=60, per=60.0, capacity=5, clock=clk)
    b.acquire(5)
    clk.advance(3)                       # 3 segundos => +3 tokens
    assert b.acquire(3) == 0.0


def test_batched_splits_evenly_and_remainder():
    items = list(range(10))
    batches = list(batched(items, 4))
    assert [len(x) for x in batches] == [4, 4, 2]
    assert sum(len(x) for x in batches) == 10


def test_batched_requires_positive_size():
    try:
        list(batched([1, 2], 0))
        assert False, "debió fallar"
    except ValueError:
        pass


def test_cache_needs_refresh():
    now = datetime(2026, 11, 5, 12, 0, 0)
    assert cache.needs_refresh(None, now, 7)                       # sin dato
    assert cache.needs_refresh(now - timedelta(days=10), now, 7)   # viejo
    assert not cache.needs_refresh(now - timedelta(days=2), now, 7)


def test_cache_missing_from_incremental():
    assert cache.missing_from(None, date(2026, 11, 5)) is None     # descargar todo
    assert cache.missing_from(date(2026, 11, 4), date(2026, 11, 5)) == date(2026, 11, 5)


def test_cache_is_fresh_enough():
    assert cache.is_fresh_enough(date(2026, 11, 4), date(2026, 11, 5), 4)
    assert not cache.is_fresh_enough(date(2026, 10, 1), date(2026, 11, 5), 4)
    assert not cache.is_fresh_enough(None, date(2026, 11, 5))
