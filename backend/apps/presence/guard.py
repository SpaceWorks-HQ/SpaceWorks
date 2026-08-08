from dataclasses import dataclass

from django.utils import timezone

from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership, MakerspaceWaiver
from apps.presence.models import PresenceSession
from apps.separability.registry import runtime_active


class MemberPresenceRequired(Exception):
    code = "membership_required"
    default_detail = "An active membership is required."


class WaiverAcceptanceRequired(Exception):
    code = "waiver_acceptance_required"
    default_detail = "Accept the current makerspace waiver first."


class PresenceRequired(Exception):
    code = "presence_required"
    default_detail = "An active presence session is required."


@dataclass(frozen=True)
class ActiveMemberPresence:
    membership: MakerspaceMembership
    accepted_waiver: MakerspaceWaiver | None
    # None only when the deployment has tombstoned check-in; no caller reads it.
    session: PresenceSession | None


def require_active_member_presence(user, makerspace):
    """Membership, then waiver, then an open check-in session.

    **The session requirement is skipped when `apps.presence` is tombstoned, and only
    that one.** This is the single place in the separability work where removing an app
    changes behaviour instead of only removing a surface, so it is worth being explicit
    about why.

    Seven member-facing flows call this as a bare precondition -- self-checkout, staff
    direct handout, public request submit, public booking and event registration, and
    the two public machine-service surfaces. A deployment that does not ship check-in
    has no session for any of them to find, so leaving the requirement hard would not
    make those flows stricter, it would make every one of them refuse forever. That is
    a broken install, which is exactly the outcome `separability.E007` exists to
    reject; a tombstone is supposed to yield a smaller system, not a stuck one.

    Membership and the waiver are still enforced, so the identity and liability factors
    are untouched, and so are the Hard Rules' non-negotiables (a box QR scan and an
    issue photo), which live in the workflow rather than here. What lapses is only
    "is this member physically checked in right now", which a deployment without
    check-in cannot answer and has decided it does not need to.
    """
    if not (
        user
        and user.is_authenticated
        and user.pk
        and user.is_active
        and user.access_status == User.AccessStatus.ACTIVE
    ):
        raise MemberPresenceRequired()
    membership = MakerspaceMembership.objects.filter(
        user=user, makerspace=makerspace, status="active"
    ).select_related("accepted_waiver").first()
    if membership is None:
        raise MemberPresenceRequired()
    waiver = MakerspaceWaiver.objects.filter(
        makerspace=makerspace, is_active=True
    ).first()
    if waiver and (
        membership.accepted_waiver_id != waiver.id
        or membership.waiver_version_accepted != waiver.version
    ):
        raise WaiverAcceptanceRequired()
    if not runtime_active("presence"):
        return ActiveMemberPresence(membership, waiver, None)
    session = PresenceSession.objects.filter(
        member=user, makerspace=makerspace, ended_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).order_by("-started_at", "-id").first()
    if session is None:
        raise PresenceRequired()
    return ActiveMemberPresence(membership, waiver, session)
