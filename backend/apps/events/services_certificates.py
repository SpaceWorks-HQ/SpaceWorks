import logging

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit import services as audit
from apps.events.certificate_rendering import render_certificate_pdf
from apps.events.certificate_storage import (
    CertificateStorageUnavailable,
    presigned_download,
    store_immutable_pdf,
)
from apps.events.exceptions import EventInvalidTransition
from apps.events.models import Event, EventAttendanceCertificate, EventRegistration
from apps.makerspaces import limits


logger = logging.getLogger(__name__)


def create_pending(response):
    registration = response.registration
    if (
        registration is None
        or registration.status != EventRegistration.Status.ATTENDED
    ):
        raise EventInvalidTransition(
            "Attendance is required before a certificate can be created."
        )
    event = registration.event
    revision = (
        EventAttendanceCertificate.objects.filter(registration=registration)
        .aggregate(value=Max("revision"))["value"]
        or 0
    ) + 1
    certificate = EventAttendanceCertificate(
        response=response,
        registration=registration,
        revision=revision,
        recipient_name=registration.name,
        event_title=event.title,
        event_starts_at=event.starts_at,
        event_ends_at=event.ends_at,
        issuer_name=event.makerspace.name,
    )
    certificate.object_key = (
        f"event-certificates/{event.makerspace_id}/{certificate.serial}.pdf"
    )
    certificate.save()
    return certificate


def render_certificate(certificate):
    claim = _claim_render(certificate.pk)
    if claim.status == EventAttendanceCertificate.Status.ACTIVE:
        return claim
    try:
        payload = render_certificate_pdf(claim)
        size, digest = store_immutable_pdf(claim.object_key, payload)
        return _activate(claim.pk, size, digest)
    except EventInvalidTransition:
        _fail_render(claim.pk)
        raise
    except Exception as exc:
        _fail_render(claim.pk)
        if isinstance(exc, CertificateStorageUnavailable):
            raise
        logger.exception("event_certificate_render_failed", extra={"certificate_id": claim.pk})
        raise CertificateStorageUnavailable from exc


def download_url(certificate):
    if certificate.status == EventAttendanceCertificate.Status.REVOKED:
        raise EventInvalidTransition("Revoked certificates cannot be downloaded.")
    if certificate.status in {
        EventAttendanceCertificate.Status.PENDING,
        EventAttendanceCertificate.Status.FAILED,
    }:
        certificate = render_certificate(certificate)
    if certificate.status != EventAttendanceCertificate.Status.ACTIVE:
        raise EventInvalidTransition("Certificate rendering is still in progress.")
    return certificate, presigned_download(certificate.object_key)


@transaction.atomic
def revoke(certificate, *, actor, reason):
    locked = EventAttendanceCertificate.objects.select_for_update().select_related(
        "registration__event__makerspace"
    ).get(pk=certificate.pk)
    if locked.status != EventAttendanceCertificate.Status.ACTIVE:
        raise EventInvalidTransition("Only an active certificate can be revoked.")
    locked.status = EventAttendanceCertificate.Status.REVOKED
    locked.revoked_at = timezone.now()
    locked.revoked_by = actor
    locked.revocation_reason = reason
    locked.save(update_fields=["status", "revoked_at", "revoked_by", "revocation_reason"])
    audit.record(
        actor,
        "event.certificate_revoked",
        makerspace=locked.registration.event.makerspace,
        target=locked,
        meta={"reason": reason, "revision": locked.revision},
    )
    return locked


@transaction.atomic
def reissue(registration, *, actor):
    locked = EventRegistration.objects.select_for_update().select_related(
        "event__makerspace"
    ).get(pk=registration.pk)
    if locked.status != EventRegistration.Status.ATTENDED:
        raise EventInvalidTransition("Attendance is required for certificate reissue.")
    if locked.attendance_certificates.exclude(
        status=EventAttendanceCertificate.Status.REVOKED
    ).exists():
        raise EventInvalidTransition("A live certificate already exists.")
    response = locked.feedback_responses.order_by("-created_at", "-id").first()
    if response is None:
        raise EventInvalidTransition("Feedback is required for certificate reissue.")
    certificate = create_pending(response)
    audit.record(
        actor,
        "event.certificate_reissued",
        makerspace=locked.event.makerspace,
        target=certificate,
        meta={"revision": certificate.revision},
    )
    return certificate


@transaction.atomic
def _claim_render(certificate_id):
    identity = EventAttendanceCertificate.objects.values(
        "registration_id", "registration__event_id"
    ).get(pk=certificate_id)
    Event.objects.select_for_update().get(pk=identity["registration__event_id"])
    registration = EventRegistration.objects.select_for_update().get(
        pk=identity["registration_id"]
    )
    row = EventAttendanceCertificate.objects.select_for_update().select_related(
        "registration__event__makerspace"
    ).get(pk=certificate_id)
    if registration.status != EventRegistration.Status.ATTENDED:
        raise EventInvalidTransition("Attendance is required to render a certificate.")
    if row.status == EventAttendanceCertificate.Status.ACTIVE:
        return row
    if row.status == EventAttendanceCertificate.Status.RENDERING:
        raise EventInvalidTransition("Certificate rendering is already in progress.")
    if row.status == EventAttendanceCertificate.Status.REVOKED:
        raise EventInvalidTransition("Revoked certificates cannot be rendered.")
    row.status = EventAttendanceCertificate.Status.RENDERING
    row.save(update_fields=["status"])
    return row


@transaction.atomic
def _activate(certificate_id, size, digest):
    identity = EventAttendanceCertificate.objects.values(
        "registration_id", "registration__event_id"
    ).get(pk=certificate_id)
    Event.objects.select_for_update().get(pk=identity["registration__event_id"])
    registration = EventRegistration.objects.select_for_update().get(
        pk=identity["registration_id"]
    )
    row = EventAttendanceCertificate.objects.select_for_update().select_related(
        "registration__event__makerspace"
    ).get(pk=certificate_id)
    if row.status == EventAttendanceCertificate.Status.ACTIVE:
        return row
    if row.status != EventAttendanceCertificate.Status.RENDERING:
        raise EventInvalidTransition("Certificate render claim was lost.")
    if registration.status != EventRegistration.Status.ATTENDED:
        row.status = EventAttendanceCertificate.Status.FAILED
        row.save(update_fields=["status"])
        raise EventInvalidTransition("Attendance changed while rendering the certificate.")
    limits.add_storage(row.registration.event.makerspace, size)
    row.size_bytes = size
    row.sha256 = digest
    row.rendered_at = timezone.now()
    row.status = EventAttendanceCertificate.Status.ACTIVE
    row.save(update_fields=["size_bytes", "sha256", "rendered_at", "status"])
    audit.record(
        None,
        "event.certificate_rendered",
        makerspace=row.registration.event.makerspace,
        target=row,
        meta={"revision": row.revision, "size_bytes": size},
    )
    return row


@transaction.atomic
def _fail_render(certificate_id):
    row = EventAttendanceCertificate.objects.select_for_update().select_related(
        "registration__event__makerspace"
    ).get(pk=certificate_id)
    if row.status != EventAttendanceCertificate.Status.RENDERING:
        return
    row.status = EventAttendanceCertificate.Status.FAILED
    row.save(update_fields=["status"])
    audit.record(
        None,
        "event.certificate_render_failed",
        makerspace=row.registration.event.makerspace,
        target=row,
        meta={"revision": row.revision},
    )
