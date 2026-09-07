"""Certification coverage report: per machine type, how many active members are trained."""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.machines.models import CertificationGrant, CertificationType
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.platform import feature_enabled, module_enabled
from apps.operations.report_types import ReportResult
from apps.operations.reports_common import limited, report_spaces

FIELDS = (
    "machine_type", "certification_type", "gating_enabled", "required_for_service",
    "required_for_booking", "active_members", "certified_members", "expiring_30d",
    "revoked_grants", "coverage_percent",
)


def build_certification_coverage(makerspace_id, *, limit=None, date_range=None, grain="day"):
    aggregate = makerspace_id is None
    now = timezone.now()
    records = []
    for space in report_spaces(makerspace_id):
        if not module_enabled(space, "machines"):
            continue
        gating = feature_enabled(space, "machines.certifications")
        active_members = MakerspaceMembership.objects.filter(makerspace=space, status="active").count()
        types = CertificationType.objects.filter(makerspace=space, is_active=True).select_related("machine_type").order_by("machine_type__name", "name")
        for row in types:
            live = CertificationGrant.objects.filter(
                certification_type=row, revoked_at__isnull=True, membership__status="active"
            ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            certified = live.values("membership_id").distinct().count()
            record = {
                "machine_type": row.machine_type.name,
                "certification_type": row.name,
                "gating_enabled": gating,
                "required_for_service": row.is_required_for_service,
                "required_for_booking": row.is_required_for_booking,
                "active_members": active_members,
                "certified_members": certified,
                "expiring_30d": live.filter(expires_at__lte=now + timedelta(days=30)).values("membership_id").distinct().count(),
                "revoked_grants": CertificationGrant.objects.filter(certification_type=row, revoked_at__isnull=False).count(),
                "coverage_percent": round(100 * certified / active_members, 1) if active_members else 0,
            }
            if aggregate:
                record["makerspace_id"] = space.id
            records.append(record)
    return ReportResult(FIELDS, limited(records, limit))
