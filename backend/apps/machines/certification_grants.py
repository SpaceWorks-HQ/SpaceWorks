"""Issuance and renewal append training evidence; neither rewrites an old expiry."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit.services import record
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import MakerspaceMembership
from . import access
from .models import CertificationGrant, CertificationType
from .notifications_certifications import notify_certification


@transaction.atomic
def issue_grant(certification_type, membership, *, actor, expires_at=None, notes="", previous=None):
    row = rbac.scope_by_makerspace(actor, CertificationType.objects.select_for_update()).get(pk=certification_type.pk)
    require_module(row.makerspace, "machines")
    if not access.can_create_machine(actor, row.makerspace_id, row.machine_type):
        raise PermissionDenied()
    membership = rbac.scope_by_makerspace(actor, MakerspaceMembership.objects.select_for_update()).get(pk=membership.pk)
    if not row.is_active:
        raise ValidationError("This certification type is inactive.")
    if membership.makerspace_id != row.makerspace_id or membership.status != "active":
        raise ValidationError({"membership_id": "An active membership in this makerspace is required."})
    if not membership.user.is_active or membership.user.access_status != "active":
        raise ValidationError({"membership_id": "This member account is unavailable."})
    if previous is not None and (previous.certification_type_id != row.pk or previous.membership_id != membership.pk):
        raise ValidationError("Renewal must retain the certification and member.")
    now = timezone.now()
    expiry = expires_at
    if expiry is None and row.validity_days:
        try:
            expiry = now + timedelta(days=row.validity_days)
        except OverflowError as exc:
            raise ValidationError({"validity_days": "Validity is outside the supported date range."}) from exc
    if expiry is not None and expiry <= now:
        raise ValidationError({"expires_at": "Expiry must be in the future."})
    grant = CertificationGrant.objects.create(
        certification_type=row, membership=membership, granted_by=actor,
        granted_at=now, expires_at=expiry, notes=notes,
    )
    meta = {"certification_type_id": row.pk, "membership_id": membership.pk,
            "expires_at": expiry.isoformat() if expiry else None}
    if previous is not None:
        meta["previous_grant_id"] = previous.pk
    record(actor, "certification.renewed" if previous else "certification.granted",
           makerspace=row.makerspace, target=grant, meta=meta)
    notify_certification(grant, "granted")
    return grant
