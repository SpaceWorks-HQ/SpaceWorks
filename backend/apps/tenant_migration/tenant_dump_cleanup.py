"""Bounded retries for Lane D unpublished bytes retained after refusal."""

from django.utils import timezone

from apps.backup import storage

from .models import TenantDumpCapture


def cleanup_refused_tenant_dump_artifacts(*, limit=100):
    rows = tuple(
        TenantDumpCapture.objects.filter(
            status__in=(
                TenantDumpCapture.Status.REFUSED,
                TenantDumpCapture.Status.FAILED,
            ),
        )
        .exclude(unpublished_object_key="")
        .order_by("updated_at", "pk")
        .values_list("pk", "unpublished_object_key")[:limit]
    )
    removed = 0
    for capture_id, key in rows:
        if not storage.delete_archive(key):
            continue
        removed += TenantDumpCapture.objects.filter(
            pk=capture_id,
            unpublished_object_key=key,
            status__in=(
                TenantDumpCapture.Status.REFUSED,
                TenantDumpCapture.Status.FAILED,
            ),
        ).update(unpublished_object_key="", updated_at=timezone.now())
    return removed
