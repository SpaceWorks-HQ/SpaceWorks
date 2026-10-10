"""The admission state machine in front of the shared activation chokepoint.

Lock order: makerspace, request, membership/role, payment. Legacy tenants continue
through the shipped flow until settings are explicitly configured.
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces import role_services
from apps.makerspaces.membership_admission_forms import encode_answers
from apps.makerspaces.membership_admission_settings import (
    AdmissionError, application_schema_for, ensure_join_allowed, settings_for, vouching_on,
)
from apps.makerspaces.membership_gating import is_staff_invitation, require_module_for_request
from apps.makerspaces.membership_helpers import _eligible_user, _member_role, _outcome, normalized_email
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MembershipRequest

OPEN_STATES = ("requested", "invited", "awaiting_vouches", "awaiting_payment")


def transition(actor, row, state, *, event=None):
    previous = row.state
    row.state = state
    row.save(update_fields=["state", "updated_at"])
    audit.record(actor, event or f"membership.{state}", makerspace=row.makerspace, target=row,
                 meta={"from_state": previous, "to_state": state})


def _prepare(row, user, policy, raw_answers):
    row.user = user
    row.admission_managed = True
    row.application_schema = application_schema_for(row.makerspace, policy)
    row.application_answers = encode_answers(row.application_schema, raw_answers)
    row.selected_plan = policy.default_plan
    row.expires_at = timezone.now() + timedelta(days=policy.request_expiry_days)
    row.rejoining = MakerspaceMembership.objects.filter(makerspace=row.makerspace, user=user).exists()
    row.save()


def request_membership(user, makerspace, application_answers=None):
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        policy = ensure_join_allowed(makerspace)
        if not policy.configured:
            from apps.makerspaces.membership_legacy import legacy_request_membership
            return legacy_request_membership(user, makerspace)
        from apps.makerspaces.guards import require_module
        require_module(makerspace, "membership")
        if not _eligible_user(user) or user.access_status != "active":
            raise ValidationError({"detail": "An unrestricted account with a verified email is required."})
        if policy.join_mode == "invite_only":
            raise AdmissionError("membership_invite_required", "This makerspace is invite-only.")
        if MakerspaceMembership.objects.filter(makerspace=makerspace, user=user, status="active").exists():
            raise ValidationError({"detail": "You are already an active member."})
        try:
            with transaction.atomic():
                row = MembershipRequest.objects.create(
                    makerspace=makerspace, user=user, invite_email=normalized_email(user.email),
                    kind="request", state="requested", requested_by=user, assigned_role=_member_role(makerspace),
                )
        except IntegrityError as exc:
            raise AdmissionError("membership_request_exists", "An open membership request already exists.") from exc
        _prepare(row, user, policy, application_answers)
        audit.record(user, "membership.requested", makerspace=makerspace, target=row)
        from apps.makerspaces.membership_notifications import notify_membership_request_pending
        notify_membership_request_pending(row)
        if vouching_on(makerspace, policy):
            transition(user, row, "awaiting_vouches")
        elif policy.join_mode == "open":
            row.approved_at = timezone.now()
            row.approved_by = user
            row.save(update_fields=["approved_at", "approved_by"])
            result = advance(user, row, policy)
            if isinstance(result, MakerspaceMembership):
                return _outcome(outcome="joined", membership=result)
        return _outcome(outcome="requested", request=row)


def claim_invitation(user, request_id, application_answers=None):
    original = MembershipRequest.objects.get(pk=request_id)
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=original.makerspace_id)
        row = MembershipRequest.objects.select_for_update().get(pk=request_id, makerspace=makerspace)
        require_module_for_request(makerspace, row)
        policy = ensure_join_allowed(makerspace)
        if is_staff_invitation(row) or not policy.configured:
            from apps.makerspaces.membership_legacy import legacy_claim_invitation
            return legacy_claim_invitation(user, request_id)
        if row.kind != "invite" or row.state != "invited" or row.user_id not in (None, user.pk):
            raise AdmissionError("membership_invitation_unclaimable", "Invitation is not claimable.")
        if normalized_email(user.email) != row.invite_email:
            raise PermissionDenied()
        if not _eligible_user(user) or user.access_status != "active":
            raise ValidationError({"detail": "An unrestricted account with a verified email is required."})
        _prepare(row, user, policy, application_answers)
        audit.record(user, "membership.invitation_claimed", makerspace=makerspace, target=row)
        from apps.makerspaces.membership_notifications import notify_membership_request_pending
        notify_membership_request_pending(row)
        if vouching_on(makerspace, policy):
            transition(user, row, "awaiting_vouches")
        elif policy.join_mode == "open":
            row.approved_at = timezone.now()
            row.approved_by = user
            row.save(update_fields=["approved_at", "approved_by"])
            return advance(user, row, policy)
        else:
            transition(user, row, "requested")
        return row


def approve_request(actor, request, assigned_role, plan=None):
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=request.makerspace_id)
        row = MembershipRequest.objects.select_for_update().get(pk=request.pk, makerspace=makerspace)
        if not rbac.can(actor, rbac.Action.MANAGE_MEMBERS, makerspace.pk):
            raise PermissionDenied()
        require_module_for_request(makerspace, row, outcome_role=assigned_role)
        policy = settings_for(makerspace)
        if is_staff_invitation(row) or (not policy.configured and not row.admission_managed):
            from apps.makerspaces.membership_legacy import legacy_approve_request
            return legacy_approve_request(actor, row, assigned_role, plan)
        ensure_join_allowed(makerspace)
        if row.kind == "invite" and not row.admission_managed:
            raise AdmissionError("membership_invitation_unclaimed", "The applicant must claim this invitation first.")
        if not row.admission_managed:
            # Pre-configuration applications retain the policy under which they were
            # submitted. An upgrade or later edit must not impose an unanswered form.
            from apps.makerspaces.membership_legacy import legacy_approve_request
            return legacy_approve_request(actor, row, assigned_role, plan)
        if row.state not in ("requested", "invited", "awaiting_vouches") or row.approved_at:
            raise AdmissionError("membership_request_terminal", "This membership request is no longer approvable.")
        if not row.user or not row.user.is_active or row.user.access_status != "active":
            raise ValidationError({"detail": "The applicant needs an unrestricted active account."})
        existing = MakerspaceMembership.objects.filter(makerspace=makerspace, user=row.user).first()
        role_services.can_assign_role(actor, makerspace, assigned_role, target_membership=existing)
        if assigned_role.granted_actions:
            raise ValidationError({"role_id": "Community admission must use a role without staff actions."})
        if plan is not None:
            row.selected_plan = plan
        elif not row.admission_managed:
            row.selected_plan = policy.default_plan
        if row.selected_plan and (row.selected_plan.makerspace_id != makerspace.pk or not row.selected_plan.is_active):
            raise ValidationError({"plan_id": "Choose an active plan in this makerspace."})
        if vouching_on(makerspace, policy):
            from apps.makerspaces.membership_vouching import require_vouches
            require_vouches(row, policy)
        row.assigned_role = assigned_role
        row.approved_at = timezone.now()
        row.approved_by = actor
        row.admission_managed = True
        row.save()
        audit.record(actor, "membership.application_approved", makerspace=makerspace, target=row)
        return advance(actor, row, policy)


def advance(actor, row, policy):
    """Re-evaluate gates under the makerspace/request locks; never grant staff actions."""
    if row.expires_at and row.expires_at <= timezone.now():
        raise AdmissionError("membership_request_expired", "This membership application has expired.")
    if vouching_on(row.makerspace, policy):
        from apps.makerspaces.membership_vouching import require_vouches
        require_vouches(row, policy)
    if not row.approved_at:
        return row
    from apps.makerspaces.membership_admission_payments import charge_admission, activate_admission
    payment = charge_admission(row, actor, policy)
    if payment and (policy.payment_timing == "before_activation" or row.state == "awaiting_payment") and payment.status == "pending":
        if row.state != "awaiting_payment":
            transition(actor, row, "awaiting_payment")
            from apps.makerspaces.membership_admission_notifications import notify_admission
            notify_admission(row, "awaiting_payment")
        return row
    if payment and payment.status == "canceled":
        raise AdmissionError("membership_payment_canceled", "The admission charge was canceled.")
    return activate_admission(actor, row)
