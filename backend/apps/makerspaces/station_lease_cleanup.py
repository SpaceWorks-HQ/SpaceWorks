"""Bounded per-tenant cleanup of expired kiosk operator leases and revocations."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.makerspaces.models_station_leases import (
    StationOperatorLease,
    StationSessionRevocation,
)


def purge_expired_operator_leases(*, now=None, tenant_limit=500):
    """Delete leases past ``expires_at + retention`` and revocations past expiry.

    One skip-and-count source-gate boundary per makerspace, in bounded PK order, so a
    migrating tenant is skipped (and counted) rather than written to.
    """
    from apps.tenant_migration.gate_runtime import fanout_tenant_write

    now = now or timezone.now()
    lease_cutoff = now - timedelta(seconds=settings.KIOSK_OPERATOR_LEASE_RETENTION_SECONDS)
    counts = {"leases": 0, "revocations": 0, "skipped": 0, "failed": 0}
    lease_tenants = StationOperatorLease.objects.filter(
        expires_at__lt=lease_cutoff
    ).values_list("makerspace_id", flat=True)
    revocation_tenants = StationSessionRevocation.objects.filter(
        expires_at__lt=now
    ).values_list("station__makerspace_id", flat=True)
    tenant_ids = sorted(set(lease_tenants) | set(revocation_tenants))[:tenant_limit]
    for makerspace_id in tenant_ids:
        with fanout_tenant_write(
            makerspace_id, operation="kiosk_operator_lease_cleanup", counts=counts
        ) as should_process:
            if not should_process:
                continue
            counts["leases"] += StationOperatorLease.objects.filter(
                makerspace_id=makerspace_id, expires_at__lt=lease_cutoff
            ).delete()[0]
            counts["revocations"] += StationSessionRevocation.objects.filter(
                station__makerspace_id=makerspace_id, expires_at__lt=now
            ).delete()[0]
    return counts
