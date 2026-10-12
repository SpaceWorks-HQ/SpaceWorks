"""Membership intervals recovered from lifecycle audits, without loading PII."""

from collections import defaultdict

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership
from apps.operations.membership_report_scope import report_queryset


def membership_intervals(space, *, actor=None, action=rbac.Action.VIEW_AUDIT):
    rows = list(report_queryset(
        MakerspaceMembership.objects.all(), space.pk, action, actor=actor,
    ).values("id", "created_at", "activated_at", "revoked_at", "status"))
    events = defaultdict(list)
    audits = report_queryset(
        AuditLog.objects.filter(
            target_type="makerspaces.makerspacemembership",
            action__in=["membership.joined", "membership.approved", "membership.revoked"],
        ), space.pk, action, actor=actor,
    ).order_by("created_at", "id").values_list("target_id", "action", "created_at")
    for target, event_action, at in audits:
        events[target].append((event_action != "membership.revoked", at))
    result = {}
    for row in rows:
        history = events[str(row["id"])]
        intervals, opened = [], None
        if not history:
            opened = row["activated_at"] or row["created_at"]
        elif not history[0][0]:
            # Legacy activation predates the first recorded revocation.
            opened = row["activated_at"] or row["created_at"]
            if opened >= history[0][1]:
                opened = row["created_at"] if row["created_at"] < history[0][1] else None
        elif row["activated_at"] and row["activated_at"] <= history[0][1]:
            # The first audit may be a role-only approval on a legacy active row.
            opened = row["activated_at"]
        for active, at in history:
            if active and opened is None:
                opened = at
            elif not active and opened is not None:
                if opened < at:
                    intervals.append((opened, at))
                opened = None
        if row["status"] == "revoked" and opened is not None:
            ended = row["revoked_at"]
            if ended and opened < ended:
                intervals.append((opened, ended))
            opened = None
        if opened is not None:
            intervals.append((opened, None))
        result[row["id"]] = intervals
    return result


def active_at(intervals, instant):
    return any(start <= instant and (end is None or instant < end) for start, end in intervals)
