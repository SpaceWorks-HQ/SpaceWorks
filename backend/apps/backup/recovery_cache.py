"""The recovery mode is read on EVERY request, so it must not be a query on every request.

The gate middleware is first in MIDDLEWARE and consults the mode before anything else, so a
naive `DeploymentRecoveryState.objects...` there adds one database round-trip to every request
the deployment ever serves -- caught by the events N+1 test, which asserts an exact query count
on an unrelated public endpoint.

Caching is safe here because invalidation is driven by a `post_save` signal on the model rather
than by call sites: there are six places that write the mode across five modules, and the
`/control/` admin can write a seventh, so an invalidate-at-each-writer scheme would be one
forgotten call away from a deployment that stays open after being quarantined. The TTL is only a
backstop for the case where a write happens somewhere the signal cannot see (a raw SQL update, a
restore from another process against a non-shared cache).

The cache must be the shared one for this to be immediate across workers -- see the CACHES
invariant: Redis when configured, DatabaseCache otherwise, never LocMem in production.
"""

from django.core.cache import cache

CACHE_KEY = "backup:deployment-recovery-mode"
CACHE_TTL_SECONDS = 5


def cached_mode(load):
    """Return the deployment mode, consulting `load` only on a cache miss.

    `load` is called with no arguments and must return the mode string. Any exception it
    raises propagates untouched, so the caller keeps its fail-closed behaviour on a database
    error -- a failure must never be cached as a usable mode.
    """
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    mode = load()
    cache.set(CACHE_KEY, mode, CACHE_TTL_SECONDS)
    return mode


def invalidate():
    cache.delete(CACHE_KEY)
