"""Locked, audited waiver publishing and acceptance."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceWaiver
from apps.makerspaces.staff_authority import lock_staff_authority


def publish_waiver(actor, makerspace, body, version):
    body, version = (body or "").strip(), (version or "").strip()
    if not body or not version:
        raise ValidationError({"detail": "Waiver body and version are required."})
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        if MakerspaceWaiver.objects.filter(makerspace=makerspace, version=version).exists():
            raise ValidationError({"version": "This version already exists."})
        now = timezone.now()
        MakerspaceWaiver.objects.select_for_update().filter(makerspace=makerspace, is_active=True).update(
            is_active=False, superseded_at=now
        )
        waiver = MakerspaceWaiver.objects.create(makerspace=makerspace, body=body, version=version,
                                                 is_active=True, created_by=actor)
        audit.record(actor, "makerspace.waiver_published", makerspace=makerspace, target=waiver,
                     meta={"version": version})
        return waiver


def deactivate_waiver(actor, makerspace):
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        waiver = MakerspaceWaiver.objects.select_for_update().filter(makerspace=makerspace, is_active=True).first()
        if waiver:
            waiver.is_active, waiver.superseded_at = False, timezone.now()
            waiver.save(update_fields=["is_active", "superseded_at"])
            audit.record(actor, "makerspace.waiver_deactivated", makerspace=makerspace, target=waiver)
        return waiver


def accept_waiver(actor_membership):
    with transaction.atomic():
        membership = MakerspaceMembership.objects.select_for_update().select_related("makerspace", "user").get(pk=actor_membership.pk)
        if membership.status != "active":
            raise ValidationError({"detail": "An active membership is required."})
        waiver = MakerspaceWaiver.objects.select_for_update().filter(makerspace=membership.makerspace, is_active=True).first()
        if waiver is None:
            return membership, None
        membership.waiver_accepted_at = timezone.now()
        membership.waiver_version_accepted = waiver.version
        membership.accepted_waiver = waiver
        membership.save(update_fields=["waiver_accepted_at", "waiver_version_accepted", "accepted_waiver"])
        audit.record(membership.user, "membership.waiver_accepted", makerspace=membership.makerspace,
                     target=membership, meta={"waiver_id": waiver.id, "version": waiver.version})
        return membership, waiver


def witness_waiver_acceptance(actor, membership_id):
    """Record server-derived legal evidence with authority rechecked under row locks."""
    with transaction.atomic():
        makerspace_id = MakerspaceMembership.objects.filter(pk=membership_id).values_list(
            "makerspace_id", flat=True
        ).first()
        if makerspace_id is None:
            raise NotFound()
        makerspace, locked_actor, _, _ = lock_staff_authority(
            actor,
            makerspace_id,
            {rbac.Action.MANAGE_MAKERSPACE, rbac.Action.ISSUE_DIRECT_LOAN},
        )
        membership = MakerspaceMembership.objects.select_for_update().get(
            pk=membership_id
        )
        if membership.makerspace_id != makerspace.id:
            raise PermissionDenied()
        if membership.status != "active":
            raise ValidationError({"detail": "An active membership is required."})

        waiver = (
            MakerspaceWaiver.objects.select_for_update()
            .filter(makerspace=makerspace, is_active=True)
            .first()
        )
        if waiver is None:
            raise ValidationError({"detail": "This makerspace has no active waiver."})

        membership.witnessed_waiver = waiver
        membership.witnessed_waiver_version = waiver.version
        membership.witnessed_by = locked_actor
        membership.witnessed_actor_snapshot = None
        membership.witnessed_at = timezone.now()
        membership.save(
            update_fields=[
                "witnessed_waiver",
                "witnessed_waiver_version",
                "witnessed_by",
                "witnessed_actor_snapshot",
                "witnessed_at",
            ]
        )
        audit.record(
            locked_actor,
            "membership.waiver_witnessed",
            makerspace=makerspace,
            target=membership,
            meta={
                "membership_id": membership.id,
                "waiver_id": waiver.id,
                "version": waiver.version,
            },
        )
        return membership, waiver
