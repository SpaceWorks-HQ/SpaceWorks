from django.apps import apps
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.utils import timezone

from apps.accounts.models import User
from apps.hardware_requests.self_checkout_models import PublicToolLoan
from apps.makerspaces.models import MakerspaceMembership, MakerspaceWaiver
from apps.makerspaces.platform import module_enabled
from apps.presence.models import PresenceSession
from apps.separability.registry import runtime_active


RECENT_LIMIT = 20
ACTIVITY_LIMIT = 50


def active_member_memberships(user):
    """Every active membership this identity may act through, archived spaces INCLUDED.

    The single source of truth for "is this caller allowed to act as a member at all".
    `apps.payments.member_access` builds its archived-tolerant surfaces on this rather than
    restating the predicate, because two copies of a security check drift and the drift is
    invisible until someone audits both. It lives here, not in payments: `apps.payments` is a
    separable app that a deployment may tombstone, and this module must keep working without
    it. Archival is deliberately NOT filtered here -- each caller applies its own rule.
    """
    if not (
        user and user.is_authenticated and user.pk and user.is_active
        and user.access_status == User.AccessStatus.ACTIVE
    ):
        return MakerspaceMembership.objects.none()
    return MakerspaceMembership.objects.select_related("makerspace", "accepted_waiver").filter(
        user=user, status="active",
    )


def active_membership(user, makerspace_id):
    membership = active_member_memberships(user).filter(
        makerspace_id=makerspace_id,
        makerspace__archived_at__isnull=True,
    ).first()
    if membership is not None:
        # Preserve request-scoped identity context (notably claim provenance) instead
        # of lazily loading a second, context-free User instance from the membership.
        membership.user = user
    return membership


def member_activity(membership):
    makerspace, member = membership.makerspace, membership.user
    now = timezone.now()
    payload = {
        "active_hardware_loans": _loans(makerspace.id, member, now),
        "recent_presence_sessions": _presence(makerspace.id, member, now),
        "currently_checked_in": PresenceSession.objects.filter(
            makerspace_id=makerspace.id, member=member, ended_at__isnull=True,
            expires_at__gt=now,
        ).exists(),
        "accountability": _accountability(membership),
    }
    if module_enabled(makerspace, "machine_service"):
        payload["print_requests"] = _printer_requests(makerspace, member)
    if module_enabled(makerspace, "bookings"):
        payload["bookings"] = _bookings(makerspace.id, member, now)
    if module_enabled(makerspace, "events"):
        payload["event_registrations"] = _event_registrations(makerspace, member)
    # runtime_active, not apps.is_installed: a tombstoned app stays in
    # INSTALLED_APPS (its migrations must remain applied), so is_installed answers
    # "are the tables there?" when this asks "are the surfaces live?".
    if module_enabled(makerspace, "machine_service") and runtime_active("machines"):
        payload["machine_service_requests"] = _machine_service_requests(makerspace.id, member)
    return payload


def _loans(makerspace_id, member, now):
    rows = PublicToolLoan.objects.filter(
        makerspace_id=makerspace_id, requester=member,
        status=PublicToolLoan.Status.CHECKED_OUT,
    ).only("target_label", "checked_out_at", "due_at").order_by("due_at", "checked_out_at")[:ACTIVITY_LIMIT]
    return [{
        "label": row.target_label,
        "checked_out_at": row.checked_out_at,
        "due_at": row.due_at,
        "overdue": bool(row.due_at and row.due_at < now),
    } for row in rows]


def _bookings(makerspace_id, member, now):
    from apps.bookings.models import Booking

    rows = Booking.objects.filter(
        space__makerspace_id=makerspace_id, member=member,
    ).select_related("space").only(
        "starts_at", "ends_at", "status", "space__name"
    )
    fields = ("starts_at", "ends_at", "status", "space_name")
    def values(queryset):
        return [dict(zip(fields, (row.starts_at, row.ends_at, row.status, row.space.name))) for row in queryset[:ACTIVITY_LIMIT]]
    return {
        "upcoming": values(rows.filter(ends_at__gte=now).order_by("starts_at", "id")),
        "past": values(rows.filter(ends_at__lt=now).order_by("-ends_at", "-id")),
    }


def _event_registrations(makerspace, member):
    from apps.events.member_history import registrations_for_space
    from apps.events.models import EventRegistration

    waitlisted_before = EventRegistration.objects.filter(
        event_id=OuterRef("event_id"), status=EventRegistration.Status.WAITLISTED,
    ).filter(
        Q(created_at__lt=OuterRef("created_at"))
        | Q(created_at=OuterRef("created_at"), id__lte=OuterRef("id"))
    ).values("event_id").annotate(total=Count("id")).values("total")[:1]
    # Shares `registrations_for_space` with the profile surfaces deliberately. The
    # waitlist-position subquery above is per-EVENT and stays local, but the question
    # "which registrations does this member hold here" must have exactly one answer:
    # when that predicate widens, a second copy here would make this endpoint and the
    # profile disagree about the same member.
    rows = registrations_for_space(makerspace, member).select_related("event").annotate(
        waitlist_position=Subquery(waitlisted_before, output_field=IntegerField())
    ).only(
        "id", "checkin_token", "status", "created_at", "event__title",
        "event__starts_at", "event__ends_at", "event__status", "event__makerspace_id",
        "registered_via_makerspace_id", "host_waiver_id",
    )
    if getattr(member, "_claim_audit_context", None) is not None:
        rows = rows.filter(event__makerspace=makerspace)
    # Two halves of one question, and they must match `EventCheckInQrView`'s filter exactly:
    # the REGISTRATION must be registered (a waitlisted row has nothing confirmable behind
    # it) and the EVENT must still be checkable. `services.cancel()` changes only
    # `Event.status` and leaves registrations REGISTERED, so gating on the registration
    # alone would advertise an admission code for a cancelled event.
    from apps.events.views_checkin import CHECKABLE_EVENT_STATUSES

    # Hosts whose active waiver a visiting registration must have accepted. Resolved once
    # rather than per row.
    from apps.makerspaces.models import MakerspaceWaiver

    ordered = list(rows.order_by("-event__starts_at", "-id")[:ACTIVITY_LIMIT])
    hosts_needing_waiver = set(
        MakerspaceWaiver.objects.filter(
            makerspace_id__in={row.event.makerspace_id for row in ordered},
            is_active=True,
        ).values_list("makerspace_id", flat=True)
    )

    def usable_token(row):
        # Must agree with `EventCheckInQrView`: a token advertised here whose QR route
        # refuses is a code that scans to nothing.
        visitor = (
            row.registered_via_makerspace_id
            and row.registered_via_makerspace_id != row.event.makerspace_id
        )
        if (
            visitor
            and row.host_waiver_id is None
            and row.event.makerspace_id in hosts_needing_waiver
        ):
            return False
        return (
            row.status == EventRegistration.Status.REGISTERED
            and row.event.status in CHECKABLE_EVENT_STATUSES
        )

    return [{
        "registration_id": row.id,
        "checkin_token": str(row.checkin_token) if usable_token(row) else None,
        "event_title": row.event.title, "starts_at": row.event.starts_at,
        "ends_at": row.event.ends_at, "status": row.status,
        "waitlist_position": row.waitlist_position if row.status == EventRegistration.Status.WAITLISTED else None,
    } for row in ordered]


def _machine_service_requests(makerspace_id, member):
    from apps.machines.models import MachineServiceRequest
    from apps.machines.service_queue_position import queue_positions_for

    rows = MachineServiceRequest.objects.filter(
        makerspace_id=makerspace_id, member=member,
    ).select_related("queue__machine_type").order_by("-created_at", "-id")[:ACTIVITY_LIMIT]
    rows = list(rows)
    positions = queue_positions_for(rows)
    result = []
    for row in rows:
        item = {"title": row.title, "status": row.status, "created_at": row.created_at, "queue_position": positions.get(row.pk)}
        if row.queue_id and row.queue.machine_type.slug == "3d_printer":
            item["machine_type"] = "3d_printer"
        result.append(item)
    return result



def _printer_requests(makerspace, member):
    from apps.machines.models import MachineServiceRequest
    from apps.machines.public_printer_service_serializers import PublicPrinterStatusSerializer
    from apps.machines.service_queue_position import queue_counts_for

    rows = list(MachineServiceRequest.objects.filter(
        makerspace=makerspace, member=member, queue__machine_type__slug="3d_printer",
    ).select_related("queue__machine_type").order_by("-created_at", "-id")[:ACTIVITY_LIMIT])
    return PublicPrinterStatusSerializer(
        rows, many=True, context={"queue_counts": queue_counts_for(rows)},
    ).data
def _presence(makerspace_id, member, now):
    rows = PresenceSession.objects.filter(
        makerspace_id=makerspace_id, member=member,
    ).only("started_at", "expires_at", "ended_at", "end_reason").order_by("-started_at", "-id")[:RECENT_LIMIT]
    return [{
        "started_at": row.started_at, "expires_at": row.expires_at,
        "ended_at": row.ended_at, "end_reason": row.end_reason,
        "active": row.ended_at is None and row.expires_at > now,
    } for row in rows]


def _accountability(membership):
    waiver = MakerspaceWaiver.objects.filter(
        makerspace_id=membership.makerspace_id, is_active=True,
    ).only("id", "version").first()
    return {
        "membership_active": membership.status == "active",
        "waiver_acceptance_required": bool(
            waiver and (membership.accepted_waiver_id != waiver.id
                        or membership.waiver_version_accepted != waiver.version)
        ),
        "restriction_code": None,
    }
