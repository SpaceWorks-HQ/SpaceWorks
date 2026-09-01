from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.hardware_requests import notifications
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.hardware_requests.workflow_errors import (
    AnonymousRequestIdempotencyConflict,
    AnonymousRequestOutstandingLimit,
    InvalidTransition,
    RequestValidationError,
    RequesterBlocked,
)
from apps.hardware_requests.workflow_utils import locked_request
from apps.inventory import availability
from apps.makerspaces.models import Makerspace
from apps.notifications.emit import emit_notification


@dataclass(frozen=True)
class RequesterSnapshot:
    """Identity captured on a request independently from its durable principal."""

    username: str
    name: str
    email: str
    phone: str
    contact_verified: bool


def submit_request(
    makerspace,
    items,
    requested_for="",
    *,
    requester_principal,
    contact_snapshot,
    audit_actor,
    idempotency_key_fingerprint="",
    payload_fingerprint="",
):
    with transaction.atomic():
        from apps.encryption.write_fence import assert_mapped_write_allowed

        assert_mapped_write_allowed(makerspace.id)
        if not contact_snapshot.contact_verified:
            # Serialize the tenant ceiling with creation. A count followed by INSERT
            # without this lock lets concurrent requests all observe spare capacity.
            makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
            existing = anonymous_idempotency_replay(
                makerspace,
                idempotency_key_fingerprint,
                payload_fingerprint,
            )
            if existing is not None:
                return existing
            _enforce_anonymous_outstanding_limit(makerspace)

        request = HardwareRequest.objects.create(
            makerspace=makerspace,
            requester=requester_principal,
            requester_username=contact_snapshot.username,
            requester_name=contact_snapshot.name,
            requester_contact_email=contact_snapshot.email,
            requester_contact_phone=contact_snapshot.phone,
            requester_contact_verified=contact_snapshot.contact_verified,
            anonymous_idempotency_key_fingerprint=idempotency_key_fingerprint,
            anonymous_payload_fingerprint=payload_fingerprint,
            status=HardwareRequest.Status.PENDING_APPROVAL,
            requested_for=requested_for,
        )
        HardwareRequestItem.objects.bulk_create(
            [
                HardwareRequestItem(
                    request=request,
                    product=item["product"],
                    requested_quantity=item["quantity"],
                )
                for item in items
            ]
        )
        audit.record(
            audit_actor,
            "request.submitted",
            makerspace=makerspace,
            target=request,
        )
        notifications.notify_request_submitted(request)
        emit_notification(
            makerspace,
            level="info",
            event="request.submitted",
            title="New hardware request",
            body=f"Hardware request #{request.pk} submitted.",
        )
        return request


def anonymous_idempotency_replay(makerspace, key_fingerprint, payload_fingerprint):
    if not key_fingerprint:
        raise RequestValidationError("An Idempotency-Key header is required.")
    existing = HardwareRequest.objects.filter(
        makerspace=makerspace,
        anonymous_idempotency_key_fingerprint=key_fingerprint,
    ).first()
    if existing is None:
        return None
    if existing.anonymous_payload_fingerprint != payload_fingerprint:
        raise AnonymousRequestIdempotencyConflict(
            "This idempotency key was already used for a different request."
        )
    return existing


def _enforce_anonymous_outstanding_limit(makerspace):
    limit = settings.ANONYMOUS_REQUEST_OUTSTANDING_LIMIT
    outstanding = HardwareRequest.objects.filter(
        makerspace=makerspace,
        status=HardwareRequest.Status.PENDING_APPROVAL,
    ).exclude(anonymous_idempotency_key_fingerprint="").count()
    if outstanding >= limit:
        raise AnonymousRequestOutstandingLimit(
            "This makerspace is not accepting more anonymous requests until "
            "pending requests are reviewed."
        )


def accept_request(actor, request, accepted=None):
    with transaction.atomic():
        locked = locked_request(request)
        if locked.status != HardwareRequest.Status.PENDING_APPROVAL:
            raise InvalidTransition(
                f"Cannot accept hardware request with status {locked.status}."
            )

        items = list(locked.items.select_related("product").order_by("product_id"))
        if accepted is not None:
            unknown = set(accepted) - {item.pk for item in items}
            if unknown:
                raise RequestValidationError(
                    "Accepted quantities reference items that are not in this request."
                )
        total = 0
        for item in items:
            # accepted is None => accept all (full). A provided map is authoritative:
            # an item not listed is declined (0), so an empty map accepts nothing.
            qty = (
                item.requested_quantity
                if accepted is None
                else int(accepted.get(item.pk, 0))
            )
            if qty < 0 or qty > item.requested_quantity:
                raise RequestValidationError(
                    "Accepted quantity must be between 0 and the requested quantity."
                )
            item.accepted_quantity = qty
            item.save(update_fields=["accepted_quantity"])
            total += qty

        if total == 0:
            raise RequestValidationError(
                "Accept at least one unit, or reject the request instead."
            )

        # reserve_for_request now runs the individual-asset guard under its own
        # product row lock, so the check and the reservation can't race apart.
        availability.reserve_for_request(locked)

        locked.status = HardwareRequest.Status.ACCEPTED
        locked.accepted_by = actor
        locked.accepted_at = timezone.now()
        locked.save(
            update_fields=["status", "accepted_by", "accepted_at", "updated_at"]
        )
        audit.record(
            actor,
            "request.accepted",
            makerspace=locked.makerspace,
            target=locked,
            meta={"accepted": {item.pk: item.accepted_quantity for item in items}},
        )
        notifications.notify_request_accepted(locked)
        return locked


def reject_request(actor, request, reason):
    reason = str(reason or "").strip()
    if not reason:
        raise RequestValidationError("Rejection reason is required.")

    with transaction.atomic():
        locked = locked_request(request)
        if locked.status != HardwareRequest.Status.PENDING_APPROVAL:
            raise InvalidTransition(
                f"Cannot reject hardware request with status {locked.status}."
            )

        locked.status = HardwareRequest.Status.REJECTED
        locked.rejection_reason = reason
        locked.save(update_fields=["status", "rejection_reason", "updated_at"])
        audit.record(
            actor,
            "request.rejected",
            makerspace=locked.makerspace,
            target=locked,
            meta={"reason": reason},
        )
        notifications.notify_request_rejected(locked)
        return locked
