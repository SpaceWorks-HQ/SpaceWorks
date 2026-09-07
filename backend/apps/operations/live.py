"""Live-update fan-out: one compact event per committed state change, per makerspace.

The audit log is already the universal record of every state change ("every state-changing
endpoint emits its audit entry"), so it is also the one place to publish from: ``record()``
schedules ``publish_audit_event`` on commit, and no workflow module needs a second hook. The
payload is deliberately tiny and PII-free — an action name and a target reference. Browsers
never render it; they invalidate the matching TanStack query keys and refetch through the
normal, RBAC-scoped endpoints.

Redis pub/sub is the transport because the broker is already there for Celery. Publishing is
best-effort: a failure is logged and swallowed, because a live hint must never break the
request that produced the audit row.
"""
import json
import logging
from datetime import UTC, datetime

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "spaceworks:live"


def makerspace_channel(makerspace_id):
    return f"{CHANNEL_PREFIX}:makerspace:{int(makerspace_id)}"


def user_channel(user_id):
    return f"{CHANNEL_PREFIX}:user:{int(user_id)}"


def live_redis_url():
    """The Redis the stream uses; empty means live updates are off for this deployment."""
    url = getattr(settings, "LIVE_REDIS_URL", "") or getattr(settings, "CELERY_BROKER_URL", "")
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False) and not getattr(settings, "LIVE_REDIS_URL", ""):
        # No broker configured (documented local flow): nothing to publish to.
        return ""
    return url


def redis_client():
    url = live_redis_url()
    if not url:
        return None
    try:
        import redis
    except ImportError:  # pragma: no cover - redis is a hard requirement in practice
        return None
    return redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)


def _payload(kind, makerspace_id, target_type, target_id, actor_id):
    return json.dumps(
        {
            "kind": kind,
            "makerspace_id": makerspace_id,
            "target_type": target_type,
            "target_id": target_id,
            "actor_id": actor_id,
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        },
        separators=(",", ":"),
    )


def publish(channel, message):
    client = redis_client()
    if client is None:
        return False
    try:
        client.publish(channel, message)
    except Exception:
        logger.warning("live_publish_failed", extra={"channel": channel})
        return False
    return True


def publish_audit_event(*, action, makerspace_id, target_type, target_id, actor_id):
    """Called by ``audit.services.record``; runs after the surrounding transaction commits."""
    if not live_redis_url():
        return

    def _send():
        message = _payload(action, makerspace_id, target_type, target_id, actor_id)
        if makerspace_id is not None:
            publish(makerspace_channel(makerspace_id), message)
        if actor_id is not None:
            publish(user_channel(actor_id), message)

    try:
        transaction.on_commit(_send, robust=True)
    except Exception:
        logger.warning("live_publish_schedule_failed", extra={"action": action})
