"""Per-tenant offline edges and bounded retention of mutable auth artifacts."""

from datetime import timedelta
import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit import services as audit
from apps.devices.models import Device, DeviceEnrollment, DeviceRequestNonce
from apps.devices.notifications import notify_device_state
from apps.devices.services_events import EventType, record_device_event
from apps.devices.services_locks import lock_tenant
from apps.makerspaces.module_registry import module_available
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.servability import servable_queryset
from apps.tenant_migration.gate_runtime import fanout_tenant_write

logger = logging.getLogger(__name__)
AUTH_CLEANUP_BATCH_SIZE = 500


def scan_offline_devices(*, now=None, batch_size=AUTH_CLEANUP_BATCH_SIZE):
    now = now or timezone.now()
    batch_size = min(max(int(batch_size), 1), 1000)
    counts = {"scanned": 0, "skipped": 0, "offline": 0, "nonces": 0, "enrollments": 0}
    if not module_available("devices"):
        return counts
    for space in servable_queryset().order_by("pk").iterator(chunk_size=100):
        if not module_enabled(space, "devices"):
            continue
        with fanout_tenant_write(
            space.pk, operation="devices.offline_scan", counts=counts,
        ) as should_process:
            if not should_process:
                continue
            try:
                with transaction.atomic():
                    space = lock_tenant(space.pk)
                    _scan_tenant(space, now, batch_size, counts)
                    counts["scanned"] += 1
            except (PermissionDenied, ValidationError):
                # Archive/uninstall can win the row lock after the initial selection.
                counts["skipped"] += 1
    logger.info("devices_offline_scan_completed", extra=counts)
    return counts


def _scan_tenant(space, now, batch_size, counts):
    # Makerspace -> Device is the same lock order as heartbeat/enrollment/revocation.
    devices = Device.objects.select_for_update().filter(
        makerspace=space, status=Device.Status.ACTIVE, offline_since__isnull=True,
    ).order_by("pk")
    for device in devices.iterator(chunk_size=100):
        last_activity = device.last_seen_at
        if last_activity is None:
            # Enrollment artifacts expire; the immutable activation event does not.
            last_activity = device.events.filter(event_type=EventType.ENROLLED).order_by(
                "-created_at"
            ).values_list("created_at", flat=True).first()
        if last_activity is None:
            continue  # Fail safe on an invalid/legacy active row with no activation.
        deadline = last_activity + timedelta(seconds=device.offline_threshold_seconds)
        if deadline > now:
            continue
        device.offline_since = deadline
        device.offline_notified_at = now
        device.save(update_fields=["offline_since", "offline_notified_at"])
        record_device_event(space, device, EventType.OFFLINE, outcome="offline")
        notify_device_state(space, device, "offline", now=now)
        counts["offline"] += 1
    _purge_auth_artifacts(space, now, batch_size, counts)


def _purge_auth_artifacts(space, now, batch_size, counts):
    nonce_ids = list(DeviceRequestNonce.objects.filter(
        # Signature skew compares integer seconds inclusively; retain one extra second
        # beyond expiry so cleanup cannot reopen a nonce in that final valid second.
        device__makerspace=space, expires_at__lt=now-timedelta(seconds=1),
    ).order_by("expires_at", "pk").values_list("pk", flat=True)[:batch_size])
    enrollment_ids = list(DeviceEnrollment.objects.filter(
        makerspace=space, expires_at__lte=now,
    ).filter(Q(used_at__isnull=False) | Q(revoked_at__isnull=False)).order_by(
        "expires_at", "pk"
    ).values_list("pk", flat=True)[:batch_size])
    nonces, _ = DeviceRequestNonce.objects.filter(pk__in=nonce_ids).delete()
    enrollments, _ = DeviceEnrollment.objects.filter(pk__in=enrollment_ids).delete()
    counts["nonces"] += nonces
    counts["enrollments"] += enrollments
    if nonces or enrollments:
        audit.record(None, "devices.auth_artifacts_purged", makerspace=space,
                     meta={"nonces": nonces, "enrollments": enrollments})


def record_activity_locked(makerspace, device, *, now):
    """Caller holds Makerspace/Device locks; reusable by signed printer handlers."""
    recovered = device.offline_since is not None
    # A timestamp taken before waiting on a lock must never move last-seen backwards.
    device.last_seen_at = max(filter(None, (device.last_seen_at, now)))
    device.offline_since = None
    device.offline_notified_at = None
    device.save(update_fields=["last_seen_at", "offline_since", "offline_notified_at"])
    if recovered:
        record_device_event(makerspace, device, EventType.RECOVERED)
        notify_device_state(makerspace, device, "recovered", now=now)
