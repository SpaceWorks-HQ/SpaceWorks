from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied

from apps.accounts.models import User
from apps.makerspaces.models_stations import Station, StationCredential
from apps.makerspaces.station_security import (
    decrypt_pin,
    encrypt_pin,
    numeric_pin,
    pin_digest,
    pin_matches,
)


class PasswordStepUpUnavailable(APIException):
    status_code = 409
    default_detail = "This account cannot use password reveal; rotate the PIN instead."
    default_code = "password_step_up_unavailable"


@transaction.atomic
def rotate(station, *, material_for):
    station = Station.objects.select_for_update().get(pk=station.pk)
    credential = (
        StationCredential.objects.select_for_update().filter(station=station).first()
    )
    version = credential.version + 1 if credential else 1
    pin = numeric_pin()
    while credential is not None and pin_matches(
        material_for(credential.version, pin), credential.pin_digest
    ):
        pin = numeric_pin()
    digest = pin_digest(material_for(version, pin))
    ciphertext = encrypt_pin(pin)
    now = timezone.now()
    if credential is None:
        credential = StationCredential.objects.create(
            station=station,
            pin_digest=digest,
            pin_ciphertext=ciphertext,
            version=version,
            is_enabled=True,
            rotated_at=now,
        )
    else:
        credential.pin_digest = digest
        credential.pin_ciphertext = ciphertext
        credential.version = version
        credential.is_enabled = True
        credential.rotated_at = now
        credential.disabled_at = None
        credential.save(
            update_fields=[
                "pin_digest", "pin_ciphertext", "version", "is_enabled",
                "rotated_at", "disabled_at", "updated_at",
            ]
        )
    return credential, pin


@transaction.atomic
def reveal(station, *, actor, current_password):
    credential = StationCredential.objects.select_for_update().filter(
        station=station,
        is_enabled=True,
    ).first()
    if credential is None:
        raise PasswordStepUpUnavailable("Rotate a station PIN before revealing it.")
    principal = User.objects.select_for_update().get(pk=actor.pk)
    if not principal.has_usable_password():
        raise PasswordStepUpUnavailable()
    if not principal.check_password(current_password):
        raise PermissionDenied("Current password is incorrect.")
    return credential, decrypt_pin(credential.pin_ciphertext)


@transaction.atomic
def disable(station):
    credential = (
        StationCredential.objects.select_for_update().filter(station=station).first()
    )
    if credential is None:
        return None
    credential.is_enabled = False
    credential.disabled_at = timezone.now()
    credential.save(update_fields=["is_enabled", "disabled_at", "updated_at"])
    return credential
