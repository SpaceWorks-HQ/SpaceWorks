"""Atomic adoption of preserved memberships after target-side email proof."""

import logging

from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit import services as audit
from apps.makerspaces import limits
from apps.makerspaces.models import (
    ImportedUserReconciliation,
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    PendingImportedMembership,
)
from apps.makerspaces.provenance import normalized_actor_snapshot


COLLISION_REASON = "membership_collision"
QUOTA_REASON = "member_quota_reached"
logger = logging.getLogger(__name__)


def _member_role(makerspace):
    role = (
        MakerspaceRole.objects.select_for_update()
        .filter(
            makerspace=makerspace,
            slug="member",
            is_default=True,
            is_protected=True,
        )
        .first()
    )
    if role is None or role.makerspace_id != makerspace.pk:
        raise ValidationError({"detail": "This makerspace has no valid Member role."})
    return role


def _validate_address_proof(user, pending):
    """Require the proven address; every occupying User, including walk-ins, counts."""
    current = User.objects.filter(pk=user.pk).first()
    if (
        current is None
        or current.email_verified_at is None
        or not current.email
        or current.email.casefold() != pending.email.casefold()
    ):
        raise ValidationError({"detail": "A verified matching email is required."})
    return current


def _validate_tenant_edges(pending, makerspace, member_role):
    if member_role.makerspace_id != makerspace.pk:
        raise ValidationError({"detail": "Member role belongs to another makerspace."})
    for field in ("accepted_waiver", "witnessed_waiver"):
        waiver_id = getattr(pending, f"{field}_id")
        if waiver_id and getattr(pending, field).makerspace_id != makerspace.pk:
            raise ValidationError({field: "Waiver belongs to another makerspace."})


def _actor(snapshot, makerspace):
    snapshot = normalized_actor_snapshot(snapshot)
    if snapshot is None:
        return None, None
    target_id = (
        ImportedUserReconciliation.objects.filter(
            makerspace=makerspace,
            source_user_id=snapshot["source_user_id"],
        )
        .values_list("target_user_id", flat=True)
        .first()
    )
    return target_id, snapshot


def _membership_values(pending, makerspace, user, member_role):
    verified_by, verified_snapshot = _actor(
        pending.verified_actor_snapshot, makerspace
    )
    activated_by, activated_snapshot = _actor(
        pending.activated_actor_snapshot, makerspace
    )
    revoked_by, revoked_snapshot = _actor(
        pending.revoked_actor_snapshot, makerspace
    )
    witnessed_by, witnessed_snapshot = _actor(
        pending.witnessed_actor_snapshot, makerspace
    )
    default = lambda name: MakerspaceMembership._meta.get_field(name).get_default()
    return {
        "makerspace": makerspace,
        "user": user,
        "assigned_role": member_role,
        "role": member_role.legacy_role or MakerspaceMembership.Role.CUSTOM,
        "receives_notifications": default("receives_notifications"),
        "can_refer": default("can_refer"),
        "can_verify": default("can_verify"),
        "verified_at": pending.verified_at,
        "verified_by_id": verified_by,
        "verified_actor_snapshot": verified_snapshot,
        "status": pending.status,
        "activated_at": pending.activated_at,
        "activated_by_id": activated_by,
        "activated_actor_snapshot": activated_snapshot,
        "revoked_at": pending.revoked_at,
        "revoked_by_id": revoked_by,
        "revoked_actor_snapshot": revoked_snapshot,
        "revocation_reason": pending.revocation_reason,
        "waiver_accepted_at": pending.waiver_accepted_at,
        "waiver_version_accepted": pending.waiver_version_accepted,
        "accepted_waiver_id": pending.accepted_waiver_id,
        "witnessed_waiver_id": pending.witnessed_waiver_id,
        "witnessed_waiver_version": pending.witnessed_waiver_version,
        "witnessed_by_id": witnessed_by,
        "witnessed_actor_snapshot": witnessed_snapshot,
        "witnessed_at": pending.witnessed_at,
    }


def _would_increase_member_count(pending, user):
    return (
        pending.status == "active"
        and user.is_active
        and user.access_status == User.AccessStatus.ACTIVE
    )


def adopt_pending_membership(user, pending):
    """Adopt once after email proof, locking makerspace before pending state.

    No optional-module guard belongs here: imported core RBAC state must remain
    adoptable while either the membership or accounts module is disabled.
    """
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(
            pk=pending.makerspace_id
        )
        pending = (
            PendingImportedMembership.objects.select_for_update(of=("self",))
            .select_related("accepted_waiver", "witnessed_waiver", "adopted_membership")
            .get(pk=pending.pk, makerspace=makerspace)
        )
        user = _validate_address_proof(user, pending)
        if pending.adopted_membership_id:
            if pending.adopted_membership.user_id != user.pk:
                raise ValidationError({"detail": "Pending import was adopted by another account."})
            return pending.adopted_membership

        existing = MakerspaceMembership.objects.select_for_update().filter(
            makerspace=makerspace, user=user
        ).first()
        if existing is not None:
            pending.unresolved_reason = COLLISION_REASON
            pending.save(update_fields=["unresolved_reason"])
            return None

        member_role = _member_role(makerspace)
        _validate_tenant_edges(pending, makerspace, member_role)
        if _would_increase_member_count(pending, user):
            try:
                limits.check_quota(makerspace, "members", adding=1)
            except ValidationError:
                pending.unresolved_reason = QUOTA_REASON
                pending.save(update_fields=["unresolved_reason"])
                return None

        values = _membership_values(pending, makerspace, user, member_role)
        try:
            with transaction.atomic():
                membership = MakerspaceMembership.objects.create(**values)
        except IntegrityError:
            if MakerspaceMembership.objects.filter(
                makerspace=makerspace, user=user
            ).exists():
                pending.unresolved_reason = COLLISION_REASON
                pending.save(update_fields=["unresolved_reason"])
                return None
            raise

        MakerspaceMembership.objects.filter(pk=membership.pk).update(
            created_at=pending.created_at
        )
        membership.created_at = pending.created_at
        pending.adopted_at = timezone.now()
        pending.adopted_membership = membership
        pending.unresolved_reason = ""
        pending.save(
            update_fields=["adopted_at", "adopted_membership", "unresolved_reason"]
        )
        meta = {"source_membership_id": pending.source_membership_id}
        if pending.accepted_waiver_id or pending.witnessed_waiver_id:
            meta["waiver_acceptance"] = "imported"
        audit.record(
            user,
            "membership.adopted_from_import",
            makerspace=makerspace,
            target=membership,
            meta=meta,
        )
        return membership


def adopt_pending_memberships_for_user(user):
    """Discover proven-email imports without letting one tenant block the account."""
    if not user.email or user.email_verified_at is None:
        return []
    pending_rows = list(
        PendingImportedMembership.objects.filter(
            email__iexact=user.email,
            adopted_membership__isnull=True,
        ).values_list("id", "makerspace_id")
    )
    adopted = []
    for pending_id, makerspace_id in pending_rows:
        candidate = PendingImportedMembership(
            id=pending_id,
            makerspace_id=makerspace_id,
        )
        try:
            membership = adopt_pending_membership(user, candidate)
        except (DatabaseError, ObjectDoesNotExist, ValidationError):
            logger.exception(
                "pending_import_adoption_failed",
                extra={
                    "pending_membership_id": pending_id,
                    "makerspace_id": makerspace_id,
                    "user_id": user.pk,
                },
            )
            continue
        if membership is not None:
            adopted.append(membership)
    return adopted
