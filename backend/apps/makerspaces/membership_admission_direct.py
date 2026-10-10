"""Default pricing for core staff-created memberships without bypassing gates."""
from apps.audit import services as audit
from apps.accounts import rbac
from rest_framework.exceptions import PermissionDenied
from apps.makerspaces.membership_admission_settings import AdmissionError, application_schema_for, settings_for, vouching_on
from apps.makerspaces.models import MakerspaceMembership, MembershipRequest
from apps.makerspaces.platform import module_enabled


def prepare_direct_admission(actor, makerspace, user, role):
    policy = settings_for(makerspace)
    if not module_enabled(makerspace, "membership") or not policy.configured:
        return None
    if policy.join_mode != "open" and not rbac.can(actor, rbac.Action.MANAGE_MEMBERS, makerspace.pk):
        raise PermissionDenied("A membership manager must decide this admission.")
    paid = policy.joining_fee > 0 or (policy.default_plan and policy.default_plan.amount > 0)
    if (policy.payment_timing == "before_activation" and paid) or vouching_on(makerspace, policy) or application_schema_for(makerspace, policy):
        raise AdmissionError("membership_application_required", "Use the admission application to complete this makerspace's join conditions.")
    row = MembershipRequest.objects.create(
        makerspace=makerspace, user=user, kind="request", state="requested",
        requested_by=actor, assigned_role=role, admission_managed=True,
        selected_plan=policy.default_plan,
        rejoining=MakerspaceMembership.objects.filter(makerspace=makerspace, user=user).exists(),
    )
    audit.record(actor, "membership.direct_admission", makerspace=makerspace, target=row)
    return row


def finish_direct_admission(actor, row, membership):
    from apps.makerspaces.membership_admission_payments import charge_admission
    from apps.makerspaces.membership_plan_services import create_term
    charge_admission(row, actor, settings_for(row.makerspace))
    if row.selected_plan_id:
        create_term(actor, membership, row.selected_plan)


def admit_walk_in(actor, makerspace, user, raw_answers=None):
    """Staff name a person; only membership managers may decide an approval gate."""
    from django.utils import timezone
    from apps.makerspaces.membership_admission import _prepare, advance, approve_request, transition
    from apps.makerspaces.membership_helpers import _member_role
    from apps.makerspaces.membership_admission_settings import ensure_join_allowed

    policy = ensure_join_allowed(makerspace)
    if policy.join_mode == "invite_only" and not rbac.can(actor, rbac.Action.MANAGE_MEMBERS, makerspace.pk):
        raise PermissionDenied("A membership manager must invite this person.")
    row = MembershipRequest.objects.create(
        makerspace=makerspace, user=user, kind="request", state="requested",
        requested_by=actor, assigned_role=_member_role(makerspace),
    )
    _prepare(row, user, policy, raw_answers)
    audit.record(actor, "membership.requested", makerspace=makerspace, target=row)
    from apps.makerspaces.membership_notifications import notify_membership_request_pending
    notify_membership_request_pending(row)
    if vouching_on(makerspace, policy):
        transition(actor, row, "awaiting_vouches")
    elif policy.join_mode == "open":
        row.approved_at = timezone.now()
        row.approved_by = actor
        row.save(update_fields=["approved_at", "approved_by"])
        return advance(actor, row, policy)
    elif rbac.can(actor, rbac.Action.MANAGE_MEMBERS, makerspace.pk):
        return approve_request(actor, row, row.assigned_role)
    return row
