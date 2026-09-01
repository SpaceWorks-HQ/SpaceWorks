"""Audited, locked lifecycle changes for makerspace memberships."""

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit import services as audit
from apps.makerspaces import role_services
from apps.makerspaces.guards import require_module
from apps.makerspaces.membership_activation import _activate_membership
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


class MembershipOutcome(dict):
    """DTO that preserves the old ``id``/``state`` read surface until J2 rewires it."""

    @property
    def id(self):
        return self.get("request_id") or self.get("membership_id")

    @property
    def pk(self):
        return self.id

    @property
    def state(self):
        return self.get("state")


def normalized_email(value):
    return (value or "").strip().lower()


def _eligible_user(user):
    return bool(user and user.is_active and user.email_verified_at and user.email)


def _approvable_user(user):
    return bool(user and user.is_active and user.email)


def _is_community_invitation(role):
    """Whether an invitation is for plain community membership rather than staff.

    `invite_membership` issues both down one path, discriminated by the assigned role:
    the protected Member role (and any custom role granting no actions) confers no
    staff authority, so it is a community invitation and belongs to the `membership`
    module. A role granting actions is a staff invitation, which must keep working
    with `membership` off -- MakerspaceMembership is core RBAC state, and locking
    staff administration behind an optional module would strand the makerspace.
    """
    return not role.granted_actions


def _member_role(makerspace):
    try:
        return MakerspaceRole.objects.get(
            makerspace=makerspace, slug="member", is_default=True, is_protected=True
        )
    except MakerspaceRole.DoesNotExist as exc:
        raise ValidationError({"detail": "This makerspace has no protected Member role."}) from exc


def _outcome(*, outcome, membership=None, request=None):
    result = MembershipOutcome(outcome=outcome)
    if membership is not None:
        result["membership_id"] = membership.pk
    if request is not None:
        result["request_id"] = request.pk
    result["state"] = membership.status if membership is not None else request.state
    return result


def request_membership(user, makerspace):
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
        role = MakerspaceRole.objects.select_for_update().get(pk=assigned_role.pk)
        if role.makerspace_id != makerspace.pk:
            raise ValidationError({"role_id": "Role must belong to this makerspace."})
        role_services.can_assign_role(actor, makerspace, role)
        if _is_community_invitation(role):
            require_module(makerspace, "membership")
        user = User.objects.filter(email__iexact=email).first()
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
                invited_by=actor, assigned_role=role, auto_activate_on_claim=True,
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


def claim_invitation(user, request_id):
    request = MembershipRequest.objects.select_related("makerspace").filter(pk=request_id).first()
    if request is None:
        raise ValidationError({"detail": "Invitation not found."})
    if request.kind != MembershipRequest.Kind.INVITE or request.state != MembershipRequest.State.INVITED:
        raise ValidationError({"detail": "Invitation is not claimable."})
    if not user.email or request.invite_email != normalized_email(user.email):
        raise PermissionDenied()
    if request.auto_activate_on_claim:
        if not _eligible_user(user):
            raise ValidationError({"detail": "An active account with a verified email is required."})
        return _activate_membership(user, request.makerspace, user, _member_role(request.makerspace),
                                    request=request, source="referral")
    return _activate_membership(user, request.makerspace, user, request.assigned_role,
                                request=request, source="claim")


def approve_request(actor, request, assigned_role):
    request = MembershipRequest.objects.select_related("makerspace", "user").get(pk=request.pk)
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=request.makerspace_id)
        request = MembershipRequest.objects.select_for_update(of=("self",)).select_related("user").get(pk=request.pk)
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


def revoke_membership(actor, membership, reason=""):
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=membership.makerspace_id)
        membership = MakerspaceMembership.objects.select_for_update().get(pk=membership.pk)
        actor_is_superadmin = actor.is_superuser or actor.role == User.Role.SUPERADMIN
        if not actor_is_superadmin and rbac.Action.MANAGE_MAKERSPACE in rbac.actions_for_membership(membership):
            raise PermissionDenied("Only a superadmin can revoke a makerspace manager.")
        changed = membership.status != "revoked"
        if changed:
            membership.status = "revoked"
            membership.revoked_at = timezone.now()
            membership.revoked_by = actor
            membership.revocation_reason = reason or ""
        membership.can_refer = False
        membership.can_verify = False
        membership.save()
        if changed:
            audit.record(actor, "membership.revoked", makerspace=makerspace, target=membership,
                         meta={"reason": membership.revocation_reason})
            from apps.makerspaces.membership_payments import cancel_for_membership

            cancel_for_membership(membership, actor)
        from apps.presence.services import end_sessions_for_membership
        end_sessions_for_membership(actor, membership)
        MembershipRequest.objects.filter(makerspace=makerspace, user=membership.user,
                                         state__in=["requested", "invited"]).update(
            state=MembershipRequest.State.REVOKED, decided_by=actor, decided_at=timezone.now()
        )
        return membership


def revoke_request(actor, request, reason=""):
    request = MembershipRequest.objects.select_related("makerspace").get(pk=request.pk)
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=request.makerspace_id)
        request = MembershipRequest.objects.select_for_update().get(pk=request.pk)
        if request.state == MembershipRequest.State.ACTIVE and request.user_id:
            membership = MakerspaceMembership.objects.filter(makerspace=makerspace, user=request.user).first()
            if membership:
                return revoke_membership(actor, membership, reason)
        request.state = MembershipRequest.State.REVOKED
        request.decided_by = actor
        request.decided_at = timezone.now()
        request.decision_note = reason or request.decision_note
        request.save()
        audit.record(actor, "membership.revoked", makerspace=makerspace, target=request)
        return request


def change_role(actor, membership, assigned_role):
    if membership.status != "active":
        raise ValidationError({"detail": "Only active memberships can change role."})
    changed = role_services.assign_role(makerspace=membership.makerspace, actor=actor,
                                        membership=membership, role=assigned_role)
    audit.record(actor, "membership.role_changed", makerspace=changed.makerspace, target=changed,
                 meta={"role_id": assigned_role.id})
    return changed
