import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.audit import services as audit
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import HardwareRequest, RequesterAccountability, ReturnEvent
from apps.hardware_requests.self_checkout_models import PublicToolLoan
from apps.operations.models import ReportMetricRollup, ReportRollupCursor


SOURCE_MODULE = "evidence_uploads"
REPORT_KEY = "evidence-compliance"
METRICS = (
    "created_count", "attached_count", "unattached_count", "object_live_count",
    "object_expired_count", "metadata_retained_count", "bytes",
)


def finalize_evidence_rollups(makerspace, *, through=None, start_at=None, actor=None):
    through = _day_start(through or timezone.now())
    with transaction.atomic():
        cursor, _ = ReportRollupCursor.objects.select_for_update().get_or_create(
            makerspace=makerspace, source_module=SOURCE_MODULE
        )
        start = _rollup_start(makerspace, cursor, through, start_at)
        changed = 0
        bucket = start
        while bucket < through:
            changed += _finalize_bucket(makerspace, bucket, bucket + timedelta(days=1), actor)
            bucket += timedelta(days=1)
        if cursor.rolled_through is None or through > cursor.rolled_through:
            cursor.rolled_through = through
        cursor.last_success_at = timezone.now()
        cursor.last_error_code = ""
        cursor.save(update_fields=("rolled_through", "last_success_at", "last_error_code", "updated_at"))
    return changed


def satisfy_retention_fence(makerspace, cutoff, *, actor=None):
    cutoff = _day_start(cutoff)
    finalize_evidence_rollups(makerspace, through=cutoff, actor=actor)
    cursor = ReportRollupCursor.objects.get(makerspace=makerspace, source_module=SOURCE_MODULE)
    if cursor.rolled_through is None or cursor.rolled_through < cutoff or cursor.last_error_code:
        raise RuntimeError("Evidence retention is blocked by an incomplete report rollup fence.")
    audit.record(actor, "report.retention_fence_satisfied", makerspace=makerspace, meta={
        "source_module": SOURCE_MODULE, "cutoff": cutoff.isoformat(),
    })
    return cursor


def _rollup_start(makerspace, cursor, through, requested):
    if requested is not None:
        return min(_day_start(requested), through)
    earliest = EvidencePhoto.objects.filter(makerspace=makerspace).order_by("created_at").values_list("created_at", flat=True).first()
    if earliest is None:
        return through
    earliest = _day_start(earliest)
    if cursor.rolled_through is None:
        return earliest
    return max(earliest, min(cursor.rolled_through - timedelta(days=7), through))


def _finalize_bucket(makerspace, start, end, actor):
    evidence = EvidencePhoto.objects.filter(makerspace=makerspace, created_at__gte=start, created_at__lt=end)
    attached_ids = _attached_ids(makerspace.id, evidence.values_list("id", flat=True))
    facts = {}
    for row in evidence.values("evidence_type").annotate(created=Count("id"), bytes=Sum("size_bytes")):
        evidence_type = row["evidence_type"]
        created = row["created"]
        attached = len(attached_ids.get(evidence_type, set()))
        facts[evidence_type] = {
            "created_count": created, "attached_count": attached,
            "unattached_count": created - attached, "object_live_count": created,
            "object_expired_count": 0, "metadata_retained_count": created,
            "bytes": row["bytes"] or 0,
        }
    changed = 0
    checksums = []
    for evidence_type, metrics in sorted(facts.items()):
        dimensions = {"evidence_type": evidence_type}
        dimension_key = f"evidence_type={evidence_type}"
        for metric_key in METRICS:
            checksum = _checksum(metric_key, dimensions, metrics[metric_key], metrics["created_count"])
            checksums.append(checksum)
            changed += _append_revision(
                makerspace, metric_key, start, end, dimension_key, dimensions,
                metrics[metric_key], metrics["created_count"], checksum, actor,
            )
    bucket_checksum = hashlib.sha256("".join(sorted(checksums)).encode()).hexdigest()
    audit.record(actor, "report.rollup_finalized", makerspace=makerspace, meta={
        "source_module": SOURCE_MODULE, "report_key": REPORT_KEY,
        "bucket": start.isoformat(), "row_count": len(checksums), "checksum": bucket_checksum,
    })
    return changed


def _append_revision(makerspace, metric, start, cutoff, dimension_key, dimensions, value, samples, checksum, actor):
    previous = ReportMetricRollup.objects.filter(
        makerspace=makerspace, report_key=REPORT_KEY, metric_key=metric,
        bucket_start=start, grain=ReportMetricRollup.Grain.DAY,
        dimension_key=dimension_key,
    ).order_by("-revision").first()
    if previous and previous.checksum == checksum:
        return 0
    revision = previous.revision + 1 if previous else 1
    rollup = ReportMetricRollup.objects.create(
        makerspace=makerspace, source_module=SOURCE_MODULE, report_key=REPORT_KEY,
        metric_key=metric, bucket_start=start, grain=ReportMetricRollup.Grain.DAY,
        dimension_key=dimension_key, dimensions=dimensions, value=Decimal(value),
        sample_count=samples, revision=revision, source_cutoff=cutoff, checksum=checksum,
    )
    audit.record(actor, "report.rollup_revision_appended", makerspace=makerspace, target=rollup, meta={
        "source_module": SOURCE_MODULE, "report_key": REPORT_KEY,
        "metric_key": metric, "bucket": start.isoformat(),
        "revision": revision, "row_count": 1, "checksum": checksum,
    })
    return 1


def _attached_ids(makerspace_id, evidence_ids):
    ids = set(evidence_ids)
    attached = set(HardwareRequest.objects.filter(makerspace_id=makerspace_id, issue_evidence_id__in=ids).values_list("issue_evidence_id", flat=True))
    attached.update(ReturnEvent.objects.filter(makerspace_id=makerspace_id, evidence_id__in=ids).values_list("evidence_id", flat=True))
    attached.update(PublicToolLoan.objects.filter(makerspace_id=makerspace_id, return_evidence_id__in=ids).values_list("return_evidence_id", flat=True))
    attached.update(RequesterAccountability.objects.filter(makerspace_id=makerspace_id, evidence_photo_id__in=ids).values_list("evidence_photo_id", flat=True))
    by_type = {}
    for evidence_type, evidence_id in EvidencePhoto.objects.filter(id__in=attached).values_list("evidence_type", "id"):
        by_type.setdefault(evidence_type, set()).add(evidence_id)
    return by_type


def _checksum(metric, dimensions, value, samples):
    payload = json.dumps([metric, dimensions, str(value), samples], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _day_start(value):
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return value.astimezone(timezone.get_current_timezone()).replace(hour=0, minute=0, second=0, microsecond=0)
