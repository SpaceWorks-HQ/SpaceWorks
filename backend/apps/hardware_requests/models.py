import uuid

from django.conf import settings
from django.db import models
from apps.encryption.mappers import ScopedPiiModelMixin


class HardwareRequest(ScopedPiiModelMixin, models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_APPROVAL = "pending_approval", "Pending Approval"
        REJECTED = "rejected", "Rejected"
        ACCEPTED = "accepted", "Accepted"
        ISSUED = "issued", "Issued"
        PARTIALLY_RETURNED = "partially_returned", "Partially Returned"
        RETURNED = "returned", "Returned"
        CLOSED_WITH_ISSUE = "closed_with_issue", "Closed with Issue"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="hardware_requests",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="hardware_requests",
    )
    requester_username = models.TextField()
    requester_name = models.TextField(blank=True, default="")
    requester_contact_email = models.TextField(blank=True)
    requester_contact_phone = models.TextField(blank=True)
    requester_contact_verified = models.BooleanField(default=True)
    anonymous_idempotency_key_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )
    anonymous_payload_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_APPROVAL,
        db_index=True,
    )
    requested_for = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    accepted_at = models.DateTimeField(null=True)
    assigned_box = models.ForeignKey(
        "boxes.Box",
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    issued_at = models.DateTimeField(null=True)
    return_due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    return_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    issue_evidence = models.OneToOneField(
        "evidence.EvidencePhoto",
        null=True,
        on_delete=models.PROTECT,
        related_name="issued_request",
    )
    issue_remark = models.TextField(blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    closed_at = models.DateTimeField(null=True)
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["makerspace", "status"]),
            models.Index(
                fields=["makerspace", "status", "-created_at"],
                name="hwreq_ms_status_created_idx",
            ),
            models.Index(
                fields=["makerspace", "status", "-issued_at", "-created_at"],
                name="hwreq_ms_status_issued_idx",
            ),
            models.Index(
                fields=["makerspace", "status", "-updated_at", "-created_at"],
                name="hwreq_ms_status_updated_idx",
            ),
            models.Index(
                fields=["makerspace", "status", "-closed_at"],
                name="hwreq_ms_status_closed_idx",
            ),
            models.Index(
                fields=["return_due_at", "id"],
                name="hwreq_return_reminder_due_idx",
                condition=models.Q(
                    return_reminder_sent_at__isnull=True,
                    status__in=["issued", "partially_returned"],
                ),
            ),
            models.Index(
                fields=["makerspace", "status"],
                name="hwreq_anon_pending_idx",
                condition=(
                    models.Q(status="pending_approval")
                    & ~models.Q(anonymous_idempotency_key_fingerprint="")
                ),
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["assigned_box"],
                condition=models.Q(
                    status__in=[
                        "issued",
                        "partially_returned",
                    ]
                ),
                name="uniq_active_loan_per_box",
            ),
            models.UniqueConstraint(
                fields=["makerspace", "anonymous_idempotency_key_fingerprint"],
                condition=~models.Q(anonymous_idempotency_key_fingerprint=""),
                name="uniq_hwreq_anon_idempotency",
            ),
        ]


class HardwareRequestItem(models.Model):
    request = models.ForeignKey(
        HardwareRequest,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        "inventory.InventoryProduct",
        on_delete=models.PROTECT,
        related_name="+",
    )
    requested_quantity = models.PositiveIntegerField()
    accepted_quantity = models.PositiveIntegerField(default=0)
    issued_quantity = models.PositiveIntegerField(default=0)
    returned_quantity = models.PositiveIntegerField(default=0)
    damaged_quantity = models.PositiveIntegerField(default=0)
    missing_quantity = models.PositiveIntegerField(default=0)
    # Units rejected as broken at handover (never issued; sent to the needs_fix bucket).
    needs_fix_quantity = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(requested_quantity__gte=1),
                name="req_item_qty_positive",
            ),
        ]


from apps.hardware_requests.return_models import (  # noqa: E402
    RequesterAccountability,
    ReturnEvent,
)
from apps.hardware_requests.asset_link_models import HardwareRequestItemAsset  # noqa: E402
from apps.hardware_requests.self_checkout_models import (  # noqa: E402
    PublicProblemReport,
    PublicToolLoan,
)
