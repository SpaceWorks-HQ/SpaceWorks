from django.db.models import Count, Q

from apps.accounts.models import DeviceGrant, DeviceRefreshFamily, NativeAppRegistration
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.platform import module_enabled
from apps.operations.report_types import ReportResult
from apps.operations.reports_common import apply_range, limited, report_spaces


FIELDS = (
    "period", "module_key", "enabled", "activations", "revocations",
    "active_accounts", "approved_apps", "active_grants", "revoked_grants",
    "reuse_detected",
)


def build_community_engagement(makerspace_id, *, limit=None, date_range=None, grain="day"):
    aggregate = makerspace_id is None
    records = []
    for space in report_spaces(makerspace_id):
        membership_enabled = module_enabled(space, "membership")
        if membership_enabled:
            memberships = MakerspaceMembership.objects.filter(makerspace=space)
            activated = apply_range(memberships, "activated_at", date_range).filter(activated_at__isnull=False).count()
            revoked = apply_range(memberships, "revoked_at", date_range).filter(revoked_at__isnull=False).count()
            _add(records, space.id, aggregate, module_key="membership", enabled=True,
                 period=_period(date_range, grain), activations=activated, revocations=revoked,
                 active_accounts=memberships.filter(status="active", user__is_active=True).values("user_id").distinct().count())
        else:
            _add(records, space.id, aggregate, module_key="membership", enabled=False, period=_period(date_range, grain))
        accounts_enabled = module_enabled(space, "member_accounts")
        if accounts_enabled:
            active = MakerspaceMembership.objects.filter(makerspace=space, status="active", user__is_active=True, user__is_walk_in=False).values("user_id").distinct().count()
            _add(records, space.id, aggregate, module_key="member_accounts", enabled=True,
                 period=_period(date_range, grain), active_accounts=active)
        else:
            _add(records, space.id, aggregate, module_key="member_accounts", enabled=False, period=_period(date_range, grain))
        mobile_enabled = module_enabled(space, "mobile")
        if mobile_enabled:
            registrations = NativeAppRegistration.objects.filter(makerspace=space)
            grants = DeviceGrant.objects.filter(registration__makerspace=space)
            reuse = DeviceRefreshFamily.objects.filter(grant__registration__makerspace=space, reuse_detected_at__isnull=False).count()
            _add(records, space.id, aggregate, module_key="mobile", enabled=True,
                 period=_period(date_range, grain), approved_apps=registrations.filter(status="approved").count(),
                 active_grants=grants.filter(status="active").count(), revoked_grants=grants.filter(status="revoked").count(),
                 reuse_detected=reuse)
        else:
            _add(records, space.id, aggregate, module_key="mobile", enabled=False, period=_period(date_range, grain))
    fields = (("makerspace_id",) + FIELDS) if aggregate else FIELDS
    return ReportResult(fields, limited(records, limit))


def _period(date_range, grain):
    if not date_range or date_range[0] is None:
        return None
    value = date_range[0].date()
    return value.replace(day=1) if grain == "month" else value


def _add(records, space_id, aggregate, **values):
    row = {field: values.get(field, 0) for field in FIELDS}
    row["enabled"] = values.get("enabled", False)
    if aggregate:
        row["makerspace_id"] = space_id
    records.append(row)
