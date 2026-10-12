"""Two-stage proof-of-possession enrollment, rotation and reactivation.

Staff open an enrollment (raw bearer token returned once, digest stored). The device
then asks for a server challenge for a candidate key and completes by signing the
enrollment message with that key. Completion re-checks everything under the
Makerspace -> Device -> Enrollment locks and swaps key, fingerprint and version in one
transaction, so a concurrent second completion loses and an old key stays
authoritative right up to the swap.
"""

import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.devices import protocol
from apps.devices.errors import DeviceKeyConflict, EnrollmentGone, EnrollmentRejected
from apps.devices.models import Device, DeviceEnrollment
from apps.devices.services_events import EventType, record_device_event
from apps.devices.services_locks import lock_tenant
from apps.ed25519 import Ed25519Error, fingerprint_public_key, verify_bytes

Purpose = DeviceEnrollment.Purpose
_PURPOSE_BY_STATUS = {
    Device.Status.PENDING: Purpose.ENROLL,
    Device.Status.ACTIVE: Purpose.ROTATE,
    Device.Status.REVOKED: Purpose.REACTIVATE,
}


def revoke_open_enrollments(actor, device, now):
    DeviceEnrollment.objects.filter(
        device=device, used_at__isnull=True, revoked_at__isnull=True
    ).update(revoked_at=now, revoked_by=actor)


def open_enrollment(actor, makerspace, device, *, now=None):
    """Issue the device's next enrollment; the caller holds both row locks."""
    now = now or timezone.now()
    purpose = _PURPOSE_BY_STATUS[device.status]
    revoke_open_enrollments(actor, device, now)
    token = secrets.token_urlsafe(32)
    enrollment = DeviceEnrollment.objects.create(
        makerspace=makerspace, device=device, purpose=purpose,
        token_digest=protocol.sha256_hex(token.encode("ascii")),
        expires_at=now + timedelta(seconds=settings.DEVICE_ENROLLMENT_TTL_SECONDS),
        created_by=actor,
    )
    event = EventType.ROTATION_STARTED if purpose == Purpose.ROTATE else EventType.ENROLLMENT_CREATED
    record_device_event(
        makerspace, device, event, actor=actor, enrollment=enrollment,
        details={"purpose": purpose},
    )
    return enrollment, token


def start_enrollment(actor, device_id):
    makerspace_id = _device_makerspace_id(device_id)
    with transaction.atomic():
        makerspace = lock_tenant(makerspace_id)
        device = Device.objects.select_for_update().get(pk=device_id)
        return open_enrollment(actor, makerspace, device)


def issue_challenge(enrollment_id, token, public_key):
    raw_key = _public_key(public_key)
    fingerprint = fingerprint_public_key(raw_key)
    with transaction.atomic():
        _makerspace, device, enrollment = _locked(enrollment_id, token)
        _assert_key_available(device, enrollment, fingerprint)
        challenge = secrets.token_bytes(32)
        enrollment.candidate_key_fingerprint = fingerprint
        enrollment.challenge_digest = protocol.sha256_hex(challenge)
        enrollment.challenge_issued_at = timezone.now()
        enrollment.save(update_fields=[
            "candidate_key_fingerprint", "challenge_digest", "challenge_issued_at",
        ])
    return protocol.b64url_encode(challenge), enrollment.expires_at


def complete_enrollment(enrollment_id, token, public_key, challenge, signature):
    raw_key = _public_key(public_key)
    fingerprint = fingerprint_public_key(raw_key)
    try:
        raw_challenge = protocol.b64url_decode(challenge, label="challenge", min_length=32, max_length=32)
        raw_signature = protocol.b64_decode(signature, label="signature", length=64)
    except protocol.ProtocolError as exc:
        raise ValidationError({"detail": str(exc)}) from exc
    with transaction.atomic():
        makerspace, device, enrollment = _locked(enrollment_id, token)
        if (
            not enrollment.challenge_digest
            or not hmac.compare_digest(enrollment.challenge_digest, protocol.sha256_hex(raw_challenge))
            or enrollment.candidate_key_fingerprint != fingerprint
        ):
            raise EnrollmentRejected()
        message = protocol.enrollment_message(
            enrollment_id=enrollment.pk, makerspace_id=makerspace.pk, device_id=device.pk,
            purpose=enrollment.purpose, fingerprint=fingerprint, challenge=raw_challenge,
        )
        try:
            verify_bytes(message, raw_signature, raw_key)
        except Ed25519Error as exc:
            raise EnrollmentRejected() from exc
        _assert_key_available(device, enrollment, fingerprint)
        now = timezone.now()
        device.public_key = protocol.b64_encode(raw_key)
        device.key_fingerprint = fingerprint
        device.key_version += 1
        device.status = Device.Status.ACTIVE
        device.revoked_at = None
        device.revoked_by = None
        if enrollment.purpose != Purpose.ROTATE:
            # A reactivation starts a fresh observation window, derived from its event.
            device.last_seen_at = None
            device.offline_since = None
            device.offline_notified_at = None
        try:
            with transaction.atomic():
                device.save(update_fields=[
                    "public_key", "key_fingerprint", "key_version", "status",
                    "revoked_at", "revoked_by", "last_seen_at",
                    "offline_since", "offline_notified_at",
                ])
        except IntegrityError as exc:
            raise DeviceKeyConflict() from exc
        enrollment.used_at = now
        enrollment.save(update_fields=["used_at"])
        event = EventType.ROTATED if enrollment.purpose == Purpose.ROTATE else EventType.ENROLLED
        record_device_event(
            makerspace, device, event, enrollment=enrollment,
            details={"purpose": enrollment.purpose},
        )
    return device


def _locked(enrollment_id, token):
    ids = DeviceEnrollment.objects.filter(pk=enrollment_id).values_list(
        "makerspace_id", "device_id"
    ).first()
    if ids is None or not isinstance(token, str):
        raise EnrollmentRejected()
    makerspace = lock_tenant(ids[0])
    device = Device.objects.select_for_update().get(pk=ids[1])
    enrollment = DeviceEnrollment.objects.select_for_update().get(pk=enrollment_id)
    digest = protocol.sha256_hex(token.encode("utf-8"))
    if not hmac.compare_digest(enrollment.token_digest, digest):
        raise EnrollmentRejected()
    if not enrollment.is_open(timezone.now()):
        raise EnrollmentGone()
    return makerspace, device, enrollment


def _assert_key_available(device, enrollment, fingerprint):
    if Device.objects.filter(key_fingerprint=fingerprint).exclude(pk=device.pk).exists():
        raise DeviceKeyConflict()
    if enrollment.purpose == Purpose.ROTATE and device.key_fingerprint == fingerprint:
        raise DeviceKeyConflict("Rotation must present a new key.")


def _public_key(value):
    try:
        return protocol.b64_decode(value, label="public key", length=32)
    except protocol.ProtocolError as exc:
        raise ValidationError({"public_key": str(exc)}) from exc


def _device_makerspace_id(device_id):
    makerspace_id = Device.objects.filter(pk=device_id).values_list(
        "makerspace_id", flat=True
    ).first()
    if makerspace_id is None:
        raise Device.DoesNotExist()
    return makerspace_id
