"""The single authority on whether a member is certified to use a machine type.

Nothing else may decide "is this member trained". The two callers are
``service_workflow_actions.submit`` (a member asking for work on a machine) and
``services_bookings.create_booking`` (a member booking a space wired to a machine type);
both call ``require_certification`` and let it raise.

Three properties are load-bearing:

- **Off by default, and a no-op when off.** Gating lives behind the
  ``machines.certifications`` feature, so an existing makerspace that upgrades keeps
  accepting every request and booking until someone opts in. `feature_enabled` also
  covers the `machines` module being uninstalled, so a bookings-only space is never
  gated by a module it does not have.
- **It fails CLOSED once on.** No resolvable membership, or a membership with no live
  grant, is a refusal — not a pass. A gate that lets an unknown identity through is not
  a gate.
- **A bypass is authorized and audited, never silent.** Only an actor with authority over
  that machine type may override, only with a stated reason, and every override writes an
  audit row naming the certification it skipped. Staff will need to let a trained-but-
  unrecorded member through; the answer is an accountable exception, not a loophole.
"""

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.audit import services as audit
from apps.machines import access
from apps.machines.models import CertificationGrant, CertificationType
from apps.makerspaces.platform import feature_enabled

FEATURE_KEY = "machines.certifications"
PURPOSE_SERVICE = "service"
PURPOSE_BOOKING = "booking"
PURPOSES = (PURPOSE_SERVICE, PURPOSE_BOOKING)


def active_grant(membership, certification_type, now=None):
    """The membership's live grant for this type, or None.

    "Live" is unrevoked AND unexpired at ``now``; expiry is read from the grant's stored
    ``expires_at`` rather than recomputed from the type's current ``validity_days``, so
    tightening the policy cannot retroactively invalidate correctly-issued training.
    """
    if membership is None or certification_type is None:
        return None
    moment = now or timezone.now()
    return (
        CertificationGrant.objects.filter(
            membership=membership,
            certification_type=certification_type,
            revoked_at__isnull=True,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=moment))
        .order_by("-granted_at", "-pk")
        .first()
    )


def live_certification_names(membership, now=None):
    """Sorted names of the membership's live grants on active types (profile + card print)."""
    if membership is None:
        return ()
    moment = now or timezone.now()
    rows = (
        CertificationGrant.objects.filter(
            membership=membership, revoked_at__isnull=True, certification_type__is_active=True
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=moment))
        .values_list("certification_type__name", flat=True)
    )
    return tuple(sorted(set(rows)))


def required_types(makerspace, machine_type, *, for_service=False, for_booking=False):
    """Active certification types for this machine type, narrowed by purpose.

    With neither flag this is the plain listing of active types (what the staff console
    reads); the gate always passes exactly one, so it never over-gates.
    """
    queryset = CertificationType.objects.filter(
        makerspace=makerspace, machine_type=machine_type, is_active=True
    ).order_by("name", "pk")
    if not (for_service or for_booking):
        return queryset
    flags = Q()
    if for_service:
        flags |= Q(is_required_for_service=True)
    if for_booking:
        flags |= Q(is_required_for_booking=True)
    return queryset.filter(flags)


def require_certification(
    makerspace, membership, machine_type, *, purpose, actor=None, override_reason=""
):
    """Raise unless ``membership`` holds every certification this purpose requires.

    A no-op while the feature is off, or when the machine type carries no requirement for
    this purpose. ``override_reason`` is honoured only for an actor with authority over
    the machine type, and every honoured override is audited.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES!r}, got {purpose!r}")
    if machine_type is None or makerspace is None:
        return
    if not feature_enabled(makerspace, FEATURE_KEY):
        return

    required = list(
        required_types(
            makerspace,
            machine_type,
            for_service=purpose == PURPOSE_SERVICE,
            for_booking=purpose == PURPOSE_BOOKING,
        )
    )
    if not required:
        return

    now = timezone.now()
    missing = [
        row for row in required if active_grant(membership, row, now) is None
    ]
    if not missing:
        return

    reason = str(override_reason or "").strip()
    if reason and _may_override(actor, makerspace, machine_type):
        for row in missing:
            audit.record(
                actor,
                "certification.override",
                makerspace=makerspace,
                target=membership,
                meta={"reason": reason, "certification_type_id": row.pk},
            )
        return

    raise PermissionDenied(
        {
            "code": "certification_required",
            "certifications": [row.name for row in missing],
        }
    )


def require_certification_for_member(
    makerspace, member, machine_type, *, purpose, actor=None, override_reason=""
):
    """`require_certification` keyed by the member USER, resolving their membership.

    Both call sites hold a user, not a membership row. Resolving here keeps the lookup
    (and its fail-closed `None`) in one place instead of duplicated in two workflows.
    """
    from apps.makerspaces.models import MakerspaceMembership

    membership = None
    if member is not None and makerspace is not None:
        membership = MakerspaceMembership.objects.filter(
            makerspace=makerspace, user=member, status="active"
        ).first()
    require_certification(
        makerspace,
        membership,
        machine_type,
        purpose=purpose,
        actor=actor,
        override_reason=override_reason,
    )


def _may_override(actor, makerspace, machine_type):
    """Authority over the machine TYPE, which is exactly what `can_create_machine` encodes.

    Tier 1 `MANAGE_MACHINES` narrowed to a role that is linked to this type, or the type's
    own direct manager. A per-machine link deliberately does not qualify: being handed one
    machine is not authority to declare who is trained on its whole class.
    """
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False
    return access.can_create_machine(actor, makerspace.pk, machine_type)
