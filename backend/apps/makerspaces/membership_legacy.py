"""Audited, locked lifecycle changes for makerspace memberships."""

from django.db import IntegrityError, transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit import services as audit
from apps.makerspaces import role_services
from apps.makerspaces.guards import require_module
from apps.makerspaces.membership_activation import _activate_membership
from apps.makerspaces.membership_revocation import (  # noqa: F401 - re-export barrel
    revoke_membership,
    revoke_request,
)
from apps.makerspaces.membership_verification import (
    set_can_refer,
    set_can_verify,
    unverify_member,
    verify_member,
)
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MembershipRequest,
)


from apps.makerspaces.membership_helpers import (
    MembershipOutcome, normalized_email, _eligible_user, _approvable_user,
    _is_community_invitation, _member_role, _outcome,
)

def legacy_request_membership(user, makerspace):
    if not _eligible_user(user):
        raise ValidationError({"detail": "An active account with a verified email is required."})
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        if makerspace.membership_policy == Makerspace.MembershipPolicy.INVITE_ONLY:
            raise ValidationError({"detail": "This makerspace is invite-only."})
        if makerspace.membership_policy == Makerspace.MembershipPolicy.OPEN:
            membership = _activate_membership(
                user, makerspace, user, _member_role(makerspace), source="open"
            )
            return _outcome(outcome="joined", membership=membership)
        if MakerspaceMembership.objects.select_for_update().filter(
            makerspace=makerspace, user=user, status="active"
        ).exists():
            raise ValidationError({"detail": "You are already an active member."})
        try:
            request = MembershipRequest.objects.create(
                makerspace=makerspace, user=user, invite_email=normalized_email(user.email),
                kind=MembershipRequest.Kind.REQUEST, state=MembershipRequest.State.REQUESTED,
                requested_by=user,
            )
        except IntegrityError as exc:
            raise ValidationError({"detail": "An open membership request already exists."}, code="conflict") from exc
        audit.record(user, "membership.requested", makerspace=makerspace, target=request)
        from apps.makerspaces.membership_notifications import notify_membership_request_pending
        notify_membership_request_pending(request)
        return _outcome(outcome="requested", request=request)


def invite_membership(actor, makerspace, invite_email, assigned_role):
    email = normalized_email(invite_email)
    if not email:
        raise ValidationError({"invite_email": "An email address is required."})
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        from apps.makerspaces.membership_admission_settings import ensure_join_allowed
        ensure_join_allowed(makerspace)
        role = MakerspaceRole.objects.select_for_update().get(pk=assigned_role.pk)
        if role.makerspace_id != makerspace.pk:
            raise ValidationError({"role_id": "Role must belong to this makerspace."})
        role_services.can_assign_role(actor, makerspace, role)
        if _is_community_invitation(role):
            require_module(makerspace, "membership")
        user = User.objects.filter(email__iexact=email).first()
        # The rule `refer_membership` already had. Approving an invitation for someone who is
        # already a member would silently rewrite their role; that is `change_role`'s job.
        if user and MakerspaceMembership.objects.filter(
            makerspace=makerspace, user=user, status="active"
        ).exists():
            raise ValidationError({"detail": "This person is already an active member."})
        try:
            request = MembershipRequest.objects.create(
                makerspace=makerspace, user=user, invite_email=email,
                kind=MembershipRequest.Kind.INVITE, state=MembershipRequest.State.INVITED,
                invited_by=actor, assigned_role=role,
            )
        except IntegrityError as exc:
            raise ValidationError({"detail": "An open invitation already exists."}, code="conflict") from exc
        audit.record(actor, "membership.invited", makerspace=makerspace, target=request,
                     meta={"role_id": role.id, "invite_email": email})
    from apps.integrations.email import send_makerspace_email
    send_makerspace_email(makerspace, "Makerspace membership invitation",
                          "You have been invited to join this makerspace. Sign in with this email to claim the invitation.",
                          [email], stream="membership", event="invitation", audience="member")
    return request


def refer_membership(actor, makerspace, invite_email):
    email = normalized_email(invite_email)
    if not email:
        raise ValidationError({"invite_email": "An email address is required."})
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        from apps.makerspaces.membership_admission_settings import ensure_join_allowed
        policy = ensure_join_allowed(makerspace)
        actor_membership = MakerspaceMembership.objects.select_for_update().filter(
            makerspace=makerspace, user=actor, status="active"
        ).first()
        # Additive: the module gate sits alongside the existing readiness checks and
        # does not replace them.
        require_module(makerspace, "membership")
        if not makerspace.referrals_enabled or not actor_membership or not actor_membership.can_refer:
            raise PermissionDenied()
        target = User.objects.filter(email__iexact=email).first()
        if target and MakerspaceMembership.objects.filter(
            makerspace=makerspace, user=target, status="active"
        ).exists():
            raise ValidationError({"detail": "This person is already an active member."})
        role = _member_role(makerspace)
        try:
            request = MembershipRequest.objects.create(
                makerspace=makerspace, user=target, invite_email=email,
                kind=MembershipRequest.Kind.INVITE, state=MembershipRequest.State.INVITED,
                invited_by=actor, assigned_role=role,
                auto_activate_on_claim=not policy.configured or policy.join_mode == "open",
            )
        except IntegrityError as exc:
            raise ValidationError({"detail": "An open invitation already exists."}, code="conflict") from exc
        audit.record(actor, "membership.referred", makerspace=makerspace, target=request,
                     meta={"role_id": role.id})
    from apps.integrations.email import send_makerspace_email
    send_makerspace_email(
        makerspace,
        "Makerspace membership invitation",
        "You have been invited to join this makerspace. Sign in with this email to claim the invitation.",
        [email], stream="membership", event="invitation", audience="member",
    )
    return request


def legacy_claim_invitation(user, request_id):
    request = MembershipRequest.objects.select_related("makerspace").filter(pk=request_id).first()
    if request is None:
        raise ValidationError({"detail": "Invitation not found."})
    if request.kind != MembershipRequest.Kind.INVITE or request.state != MembershipRequest.State.INVITED:
        raise ValidationError({"detail": "Invitation is not claimable."})
    if not user.email or request.invite_email != normalized_email(user.email):
        raise PermissionDenied()
    from apps.makerspaces.membership_gating import require_module_for_request

    # A community invitation or a referral is the module's own path (A7); a staff
    # invitation keeps working with the module off.
    require_module_for_request(request.makerspace, request)
    if request.auto_activate_on_claim:
        if not _eligible_user(user):
            raise ValidationError({"detail": "An active account with a verified email is required."})
        return _activate_membership(user, request.makerspace, user, _member_role(request.makerspace),
                                    request=request, source="referral")
    return _activate_membership(user, request.makerspace, user, request.assigned_role,
                                request=request, source="claim")


def legacy_approve_request(actor, request, assigned_role, plan=None):
    """Activate the membership; with a `plan`, open its first term in the SAME transaction.

    One transaction, so a refused term (an inactive or foreign plan) also refuses the
    approval instead of leaving an active member the 400 told staff was not created.
    """
    with transaction.atomic():
        membership = _approve_request(actor, request, assigned_role)
        if plan is not None:
            from apps.makerspaces.membership_plan_services import create_term

            create_term(actor, membership, plan)
    return membership


def _approve_request(actor, request, assigned_role):
    request = MembershipRequest.objects.select_related("makerspace", "user").get(pk=request.pk)
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=request.makerspace_id)
        request = MembershipRequest.objects.select_for_update(of=("self",)).select_related("user").get(pk=request.pk)
        if (request.assigned_role_id and request.assigned_role.granted_actions
                and not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk)):
            raise PermissionDenied("Managing staff invitations requires makerspace administration.")
        if request.state not in (MembershipRequest.State.REQUESTED, MembershipRequest.State.INVITED):
            raise ValidationError({"detail": "This membership request is no longer open."})
        if not _approvable_user(request.user):
            raise ValidationError({"detail": "The invited member needs an active account."})
        if assigned_role.makerspace_id != makerspace.pk:
            raise ValidationError({"role_id": "Role must belong to this makerspace."})
        existing = MakerspaceMembership.objects.select_for_update().filter(
            makerspace=makerspace, user=request.user
        ).first()
        role_services.can_assign_role(actor, makerspace, assigned_role, target_membership=existing)
        return _activate_membership(actor, makerspace, request.user, assigned_role,
                                    request=request, source="approval")

