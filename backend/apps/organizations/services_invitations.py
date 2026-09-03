import hashlib
import secrets
from datetime import timedelta

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit import services as audit
from apps.organizations import governance
from apps.organizations.access import is_superadmin, lock_governance_membership
from apps.organizations.exceptions import (
    InvitationExpired,
    InvitationGrantChanged,
    InvitationRedeemed,
    InvitationRevoked,
    MembershipSuspended,
)
from apps.organizations.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
)


DEFAULT_EXPIRY_DAYS = 7
MAX_EXPIRY_DAYS = 30


def _clean_actions(values, allowed, field):
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise ValidationError({field: "Use a list of action values."})
    unknown = set(values) - set(allowed)
    if unknown:
        raise ValidationError({field: f"Unknown action value: {sorted(unknown)[0]}."})
    return sorted(set(values))


def _digest(token):
    value = str(token or "").strip()
    if not 20 <= len(value) <= 200:
        raise Http404()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _authority_actions(actor, membership):
    if is_superadmin(actor):
        return set(governance.GOVERNANCE_ACTIONS), set(rbac.ORGANIZATION_GRANTABLE_ACTIONS)
    return (
        governance.actions_for_membership(membership),
        rbac.actions_for_organization_membership(membership),
    )


@transaction.atomic
def create_invitation(
    organization,
    *,
    actor,
    governance_actions,
    granted_actions,
    expires_in_days=DEFAULT_EXPIRY_DAYS,
):
    proposed_governance = _clean_actions(
        governance_actions, governance.GOVERNANCE_ACTIONS, "governance_actions"
    )
    proposed_grants = _clean_actions(
        granted_actions, rbac.ORGANIZATION_GRANTABLE_ACTIONS, "granted_actions"
    )
    if not 1 <= expires_in_days <= MAX_EXPIRY_DAYS:
        raise ValidationError(
            {"expires_in_days": f"Use a value from 1 to {MAX_EXPIRY_DAYS}."}
        )

    locked_org = Organization.objects.select_for_update().get(pk=organization.pk)
    membership = lock_governance_membership(
        actor, locked_org, governance.MANAGE_ORGANIZATION_MEMBERS
    )
    held_governance, held_grants = _authority_actions(actor, membership)
    if not set(proposed_governance).issubset(held_governance):
        raise PermissionDenied("You cannot grant organization authority you do not hold.")
    if not set(proposed_grants).issubset(held_grants):
        raise PermissionDenied("You cannot grant makerspace actions you do not hold.")

    raw_token = secrets.token_urlsafe(32)
    invitation = OrganizationInvitation.objects.create(
        organization=locked_org,
        token_digest=_digest(raw_token),
        governance_actions=proposed_governance,
        granted_actions=proposed_grants,
        expires_at=timezone.now() + timedelta(days=expires_in_days),
        created_by=actor,
    )
    audit.record(
        actor,
        "organization.invitation_created",
        target=invitation,
        meta={
            "organization_id": locked_org.pk,
            "governance_actions": proposed_governance,
            "granted_actions": proposed_grants,
            "expires_at": invitation.expires_at.isoformat(),
        },
    )
    return invitation, raw_token


@transaction.atomic
def revoke_invitation(invitation, *, actor):
    locked = OrganizationInvitation.objects.select_for_update().get(pk=invitation.pk)
    organization = Organization.objects.select_for_update().get(pk=locked.organization_id)
    lock_governance_membership(
        actor, organization, governance.MANAGE_ORGANIZATION_MEMBERS
    )
    if locked.redeemed_at is not None:
        raise InvitationRedeemed()
    if locked.revoked_at is None:
        locked.revoked_at = timezone.now()
        locked.save(update_fields=["revoked_at", "updated_at"])
        audit.record(
            actor,
            "organization.invitation_revoked",
            target=locked,
            meta={"organization_id": organization.pk},
        )
    return locked


@transaction.atomic
def redeem_invitation(token, *, actor):
    invitation = OrganizationInvitation.objects.select_for_update().filter(
        token_digest=_digest(token)
    ).first()
    if invitation is None:
        raise Http404()
    organization = Organization.objects.select_for_update().get(pk=invitation.organization_id)
    locked_actor = User.objects.select_for_update().get(pk=actor.pk)
    if (
        not locked_actor.is_active
        or locked_actor.access_status != User.AccessStatus.ACTIVE
        or locked_actor.must_change_password
        or not organization.is_active
    ):
        raise PermissionDenied()
    if invitation.redeemed_at is not None:
        raise InvitationRedeemed()
    if invitation.revoked_at is not None:
        raise InvitationRevoked()
    if invitation.expires_at <= timezone.now():
        raise InvitationExpired()

    memberships = list(
        OrganizationMembership.objects.select_for_update()
        .filter(
            organization=organization,
            user_id__in={invitation.created_by_id, locked_actor.pk} - {None},
        )
        .order_by("pk")
    )
    by_user = {membership.user_id: membership for membership in memberships}
    creator_membership = by_user.get(invitation.created_by_id)
    if invitation.created_by_id is None:
        raise InvitationGrantChanged()
    creator = User.objects.select_for_update().filter(pk=invitation.created_by_id).first()
    if (
        creator is None
        or not creator.is_active
        or creator.access_status != User.AccessStatus.ACTIVE
        or creator.must_change_password
    ):
        raise InvitationGrantChanged()
    held_governance, held_grants = _authority_actions(creator, creator_membership)
    if not set(invitation.governance_actions).issubset(held_governance):
        raise InvitationGrantChanged()
    if not set(invitation.granted_actions).issubset(held_grants):
        raise InvitationGrantChanged()

    membership = by_user.get(locked_actor.pk)
    if membership is not None and membership.status == OrganizationMembership.Status.SUSPENDED:
        raise MembershipSuspended()
    if membership is None:
        membership = OrganizationMembership.objects.create(
            organization=organization,
            user=locked_actor,
            governance_actions=invitation.governance_actions,
            granted_actions=invitation.granted_actions,
            created_by=creator,
        )
    else:
        membership.governance_actions = sorted(
            set(membership.governance_actions or []) | set(invitation.governance_actions)
        )
        membership.granted_actions = sorted(
            set(membership.granted_actions or []) | set(invitation.granted_actions)
        )
        membership.save(
            update_fields=["governance_actions", "granted_actions", "updated_at"]
        )

    invitation.redeemed_at = timezone.now()
    invitation.redeemed_by = locked_actor
    invitation.save(update_fields=["redeemed_at", "redeemed_by", "updated_at"])
    audit.record(
        locked_actor,
        "organization.invitation_redeemed",
        target=invitation,
        meta={"organization_id": organization.pk, "membership_id": membership.pk},
    )
    return membership
