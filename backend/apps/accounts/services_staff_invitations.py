"""Tenant staff invitations: fresh grants, current inviter ceiling, encrypted address."""

import secrets
from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.accounts.mfa_challenges import digest
from apps.accounts.models import User
from apps.accounts.models_staff_invitations import StaffInvitation
from apps.audit.services import record
from apps.makerspaces.models import Makerspace, MakerspaceRole
from apps.makerspaces.role_services import can_assign_role
from apps.makerspaces.secrets import encrypt_value
from apps.makerspaces.platform import feature_enabled
from apps.tenant_migration.gate_runtime import tenant_write


def scoped(actor):
    return rbac.scope_by_action(actor, rbac.Action.MANAGE_MAKERSPACE,
                                StaffInvitation.objects.all())


def authority(actor, space, role=None):
    if not feature_enabled(space, "staff.invitations"):
        raise ValidationError("Staff invitations are disabled for this makerspace.")
    if (not actor.is_active or actor.is_tenant_dump_stub or actor.must_change_password
            or actor.access_status != User.AccessStatus.ACTIVE):
        raise PermissionDenied()
    if not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, space.pk):
        raise PermissionDenied()
    if role is not None:
        if not role.granted_actions:
            raise ValidationError("Choose a staff role with actions.")
        can_assign_role(actor, space, role)


def create(actor, space_id, *, email, role_id, expires_in_days=7):
    with tenant_write(space_id):
        space = get_object_or_404(rbac.scope_by_action(actor, rbac.Action.MANAGE_MAKERSPACE,
                                    Makerspace.objects.select_for_update(), "id"), pk=space_id)
        role = MakerspaceRole.objects.select_for_update().filter(pk=role_id, makerspace=space).first()
        if role is None:
            raise ValidationError("Choose a role in this makerspace.")
        authority(actor, space, role)
        raw = secrets.token_urlsafe(32)
        invitation = StaffInvitation.objects.create(
            makerspace=space, role=role, email_ciphertext=encrypt_value(email.strip().lower()),
            granted_actions=sorted(role.granted_actions), token_digest=digest(raw),
            expires_at=timezone.now() + timedelta(days=expires_in_days), created_by=actor,
        )
        record(actor, "staff.invitation_created", makerspace=space, target=invitation,
               meta={"role_id": role.pk, "expires_at": invitation.expires_at.isoformat()})
    return invitation, raw


def mutate(actor, invitation, *, resend=False):
    with tenant_write(invitation.makerspace_id):
        space = Makerspace.objects.select_for_update().get(pk=invitation.makerspace_id)
        row = scoped(actor).select_for_update().get(pk=invitation.pk, makerspace=space)
        role = MakerspaceRole.objects.select_for_update().get(pk=row.role_id, makerspace=space)
        authority(actor, space, role if resend else None)
        if row.accepted_at or (resend and row.revoked_at):
            raise ValidationError("This invitation is no longer available.")
        raw = None
        if resend:
            raw = secrets.token_urlsafe(32)
            row.token_digest = digest(raw)
            row.granted_actions = sorted(role.granted_actions)
            row.expires_at = timezone.now() + timedelta(days=7)
            row.failed_attempts = 0
            row.created_by = actor
        else:
            row.revoked_at = timezone.now()
        row.save()
        record(actor, "staff.invitation_resent" if resend else "staff.invitation_revoked",
               makerspace=space, target=row)
    return row, raw
