"""Registration status transitions that must also settle live device authority."""

from django.db import transaction
from django.utils import timezone

from apps.accounts.models_devices import (
    DeviceGrant,
    DeviceRefreshFamily,
    NativeAppRegistration,
)
from apps.audit import services as audit


@transaction.atomic
def revoke_registration(registration, *, actor=None):
    """Revoke an app AND permanently revoke the device authority it issued.

    Status checks alone only SUSPEND access while the row stays revoked: a device that
    never refreshes keeps its grant and its still-valid refresh token, so re-approving the
    same row later silently resurrects them. Revocation must therefore be a settled state
    on the grants themselves, not a derived one.
    """
    locked = (
        NativeAppRegistration.objects.select_for_update()
        .filter(pk=registration.pk)
        .first()
    )
    if locked is None:
        return None
    now = timezone.now()
    grants = DeviceGrant.objects.filter(registration=locked).exclude(
        status=DeviceGrant.Status.REVOKED
    )
    grant_ids = list(grants.values_list("pk", flat=True))
    DeviceRefreshFamily.objects.filter(grant_id__in=grant_ids).update(
        revoked_at=now
    )
    grants.update(status=DeviceGrant.Status.REVOKED, revoked_at=now)
    locked.status = NativeAppRegistration.Status.REVOKED
    locked.revoked_at = now
    locked.save(update_fields=["status", "revoked_at", "updated_at"])
    audit.record(
        actor,
        "native_app.revoked",
        makerspace=locked.makerspace,
        target=locked,
        meta={"grants_revoked": len(grant_ids)},
    )
    return locked
