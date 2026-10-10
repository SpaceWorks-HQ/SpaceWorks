"""Locked capability delegation and per-makerspace member verification."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace, MakerspaceMembership


def _set_capability(actor, membership, field, value):
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=membership.makerspace_id)
        require_module(makerspace, "membership")
        membership = MakerspaceMembership.objects.select_for_update().get(pk=membership.pk)
        if not rbac.can(actor, rbac.Action.MANAGE_MEMBERS, makerspace.pk):
            raise PermissionDenied()
        if value and membership.status != "active":
            # Revocation clears both delegations; granting one back to a revoked row would
            # only be undone again by reactivation, and reads as authority meanwhile.
            raise ValidationError({"detail": "Only an active membership can be delegated."})
        setattr(membership, field, bool(value))
        membership.save(update_fields=[field])
        audit.record(actor, f"membership.{field}_changed", makerspace=makerspace,
                     target=membership, meta={"value": bool(value)})
        return membership


def set_can_refer(actor, membership, value):
    return _set_capability(actor, membership, "can_refer", value)


def set_can_verify(actor, membership, value):
    return _set_capability(actor, membership, "can_verify", value)


def _verification_target(actor, membership):
    makerspace = Makerspace.objects.select_for_update().get(pk=membership.makerspace_id)
    require_module(makerspace, "membership")
    membership = MakerspaceMembership.objects.select_for_update().get(pk=membership.pk)
    if membership.status != "active":
        raise ValidationError({"detail": "Only active memberships can be verified."})
    manager = rbac.can(actor, rbac.Action.MANAGE_MEMBERS, makerspace.pk)
    actor_membership = rbac.scope_by_makerspace(
        actor, MakerspaceMembership.objects.select_for_update(),
    ).filter(
        makerspace=makerspace, user=actor, status="active"
    ).first()
    if not manager and not (actor_membership and actor_membership.can_verify):
        raise PermissionDenied()
    if not manager and membership.user_id == actor.pk:
        raise PermissionDenied("Delegated verifiers cannot verify themselves.")
    return makerspace, membership


def verify_member(actor, membership):
    with transaction.atomic():
        makerspace, membership = _verification_target(actor, membership)
        newly_verified = membership.verified_at is None
        membership.verified_at = timezone.now()
        membership.verified_by = actor
        membership.save(update_fields=["verified_at", "verified_by"])
        audit.record(actor, "membership.verified", makerspace=makerspace, target=membership)
        if newly_verified:
            from apps.makerspaces.membership_notifications import send_member_verified
            send_member_verified(membership)
        return membership


def unverify_member(actor, membership):
    with transaction.atomic():
        makerspace, membership = _verification_target(actor, membership)
        membership.verified_at = None
        membership.verified_by = None
        membership.save(update_fields=["verified_at", "verified_by"])
        audit.record(actor, "membership.unverified", makerspace=makerspace, target=membership)
        return membership
