"""Bounded in-process cache for successfully unwrapped active DEKs."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock
from time import monotonic

from django.conf import settings


_cache_disabled = ContextVar("pii_dek_cache_disabled", default=False)


@dataclass(frozen=True)
class CacheKey:
    makerspace_id: int
    version: int
    broker_backend: str
    broker_key_id: str


class DekCache:
    def __init__(self):
        self._entries = {}
        self._lock = RLock()

    @staticmethod
    def _ttl():
        return max(0, settings.PII_DEK_CACHE_TTL_SECONDS)

    def get(self, key):
        if _cache_disabled.get() or not self._ttl():
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, dek = entry
            if monotonic() >= expires_at:
                self._entries.pop(key, None)
                return None
            return dek

    def set(self, key, dek):
        if _cache_disabled.get():
            return
        ttl = self._ttl()
        if not ttl:
            return
        with self._lock:
            self._entries[key] = (monotonic() + ttl, dek)

    def invalidate(self, makerspace_id, version=None):
        with self._lock:
            for key in tuple(self._entries):
                if key.makerspace_id == makerspace_id and (
                    version is None or key.version == version
                ):
                    self._entries.pop(key, None)

    def clear(self):
        with self._lock:
            self._entries.clear()


dek_cache = DekCache()


def key_for(key_row):
    return CacheKey(
        makerspace_id=key_row.makerspace_id,
        version=key_row.version,
        broker_backend=key_row.broker_backend,
        broker_key_id=key_row.broker_key_id,
    )


@contextmanager
def dek_cache_disabled():
    """Disable DEK caching for a short-lived sensitive operation.

    Entries are cleared on both sides of the scope so this process does not retain
    cache-owned references to plaintext keys. This is best-effort clearing, not
    secure zeroization: the broker boundary accepts immutable ``bytes`` and
    ``WrappedDek`` is frozen, so copies cannot be wiped in place.
    """
    dek_cache.clear()
    token = _cache_disabled.set(True)
    try:
        yield
    finally:
        dek_cache.clear()
        _cache_disabled.reset(token)
