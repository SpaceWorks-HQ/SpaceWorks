from dataclasses import dataclass, replace

from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.claim_sessions import claim_context
from apps.makerspaces.models import MakerspaceMembership, MakerspaceWaiver
from apps.makerspaces.servability import is_servable
from apps.makerspaces.waiver_state import current_acceptance
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


def require_active_member(user, makerspace):
    """Identity, membership and waiver -- the half that is not about being here.

    Split out of `require_active_member_presence` for the flows where physical presence
    is not the relevant factor. **Event registration is the caller:** signing up is
    planning to attend rather than attending, so a member registering in advance from
    home cannot hold an open session, and a member of a collaborating space can never
    hold one at the host at all. Presence for an event is established later, by the
    staff-scanned QR check-in, which is stronger evidence than a self-declared session
    because a staffer observed the person.

    Returns the same shape with `session=None`, because this half never looked for one.
    Keeping it as the single implementation of the membership and waiver rules is the
    point: two copies would drift, and the copy that drifted would be an auth rule.
    """
    if not is_servable(makerspace) or not (
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
    context = claim_context(user)
    if context is not None and membership.pk != context.membership_id:
        raise MemberPresenceRequired()
    waiver = MakerspaceWaiver.objects.filter(
        makerspace=makerspace, is_active=True
    ).first()
    if waiver and not current_acceptance(membership, active_waiver=waiver):
        raise WaiverAcceptanceRequired()
    return ActiveMemberPresence(membership, waiver, None)


def require_active_member_presence(user, makerspace):
    """Membership, then waiver, then an open check-in session.

    **The session requirement is skipped when `apps.presence` is tombstoned, and only
    that one.** This is the single place in the separability work where removing an app
    changes behaviour instead of only removing a surface, so it is worth being explicit
    about why.

    Six member-facing surfaces call this as a bare precondition -- self-checkout, staff
    direct handout, public request submit, public booking, and the two public
    machine-service surfaces. A deployment that does not ship check-in has no session for
    any of them to find, so leaving the requirement hard would not make those flows
    stricter, it would make every one of them refuse forever. That is a broken install,
    which is exactly the outcome `separability.E007` exists to reject; a tombstone is
    supposed to yield a smaller system, not a stuck one.

    Membership and the waiver are still enforced, so the identity and liability factors
    are untouched, and so are the Hard Rules' non-negotiables (a box QR scan and an
    issue photo), which live in the workflow rather than here. What lapses is only
    "is this member physically checked in right now", which a deployment without
    check-in cannot answer and has decided it does not need to.

    **Event registration used to be a seventh caller and deliberately is not any more**
    -- see `require_active_member`. These are all hardware and facility actions, where
    "is this member here right now" is the whole question; registering for a future event
    is not.
    """
    active = require_active_member(user, makerspace)
    if not runtime_active("presence"):
        return active
    session = PresenceSession.objects.filter(
        member=user, makerspace=makerspace, ended_at__isnull=True,
        expires_at__gt=timezone.now(),
    )
    context = claim_context(user)
    if context is not None:
        session = session.filter(
            created_via_claim_session__session_id=context.session_id,
            expires_at__lte=context.absolute_expires_at,
        )
    session = session.order_by("-started_at", "-id").first()
    if session is None:
        raise PresenceRequired()
    return replace(active, session=session)
