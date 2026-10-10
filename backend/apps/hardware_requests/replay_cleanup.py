"""Bounded coordination expiry; immutable evidence and domain rows survive."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.hardware_requests.models_replay import ReplayCommand
from apps.hardware_requests.replay_claims import fail_locked
from apps.hardware_requests.replay_failures import ReplayFailure
from apps.hardware_requests.replay_records import lease_snapshot


def cleanup_replay_commands(*, now=None, tenant_limit=500):
    from apps.tenant_migration.gate_runtime import fanout_tenant_write

    now = now or timezone.now()
    cutoff = now - timedelta(seconds=settings.KIOSK_REPLAY_RETENTION_SECONDS)
    stale = now - timedelta(seconds=settings.KIOSK_REPLAY_CLAIM_TIMEOUT_SECONDS)
    counts = {"expired": 0, "deleted": 0, "skipped": 0, "failed": 0}
    tenants = ReplayCommand.objects.filter(expires_at__lte=now).order_by("makerspace_id").values_list(
        "makerspace_id", flat=True,
    ).distinct()[:tenant_limit]
    for makerspace_id in tenants:
        with fanout_tenant_write(makerspace_id, operation="kiosk_replay_cleanup", counts=counts) as allowed:
            if not allowed:
                continue
            with transaction.atomic():
                pending = ReplayCommand.objects.select_for_update().filter(
                    makerspace_id=makerspace_id, expires_at__lte=now,
                ).filter(Q(state="prepared") | Q(state="claimed", claimed_at__lte=stale)).order_by("pk")
                for command in pending[:settings.KIOSK_REPLAY_CLEANUP_BATCH_SIZE]:
                    fail_locked(command, ReplayFailure("command_expired"), lease_snapshot(command))
                    counts["expired"] += 1
                ids = list(ReplayCommand.objects.filter(
                    makerspace_id=makerspace_id, state__in=("succeeded", "failed"),
                    completed_at__lte=cutoff, successors__isnull=True,
                ).order_by("pk").values_list("pk", flat=True)[:settings.KIOSK_REPLAY_CLEANUP_BATCH_SIZE])
                counts["deleted"] += ReplayCommand.objects.filter(pk__in=ids).delete()[0]
    return counts
