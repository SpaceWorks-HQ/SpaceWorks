from django.conf import settings
from django.db import models


class PublicToolLoan(models.Model):
    class Source(models.TextChoices):
        PUBLIC_SELF_CHECKOUT = "public_self_checkout", "Public Self Checkout"
        ADMIN_DIRECT = "admin_direct", "Admin Direct"

    class Status(models.TextChoices):
        CHECKED_OUT = "checked_out", "Checked Out"
        RETURNED = "returned", "Returned"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.PROTECT,
        related_name="public_tool_loans",
    )
    qr_code = models.ForeignKey(
        "boxes.QrCode",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="public_tool_loans",
    )
    container = models.ForeignKey(
        "boxes.Box",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    request = models.OneToOneField(
        "hardware_requests.HardwareRequest",
        on_delete=models.PROTECT,
        related_name="public_tool_loan",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="public_tool_loans",
    )
    target_type = models.CharField(max_length=20)
    target_id = models.PositiveIntegerField()
    target_label = models.CharField(max_length=200)
    asset_ids = models.JSONField(default=list, blank=True)
    # Every QR bundled into this loan. The qr_code FK holds only the first (the
    # partial-unique constraint permits one active loan per qr_code); qr_ids tracks
    # the rest so a secondary QR in a multi-QR direct handout can't be re-issued.
    qr_ids = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CHECKED_OUT,
        db_index=True,
    )
    source = models.CharField(
        max_length=32,
        choices=Source.choices,
        default=Source.PUBLIC_SELF_CHECKOUT,
        db_index=True,
    )
    checked_out_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    # OneToOne (not FK): one return photo per handover — a given evidence row can
    # back at most one direct-loan return, mirroring ReturnEvent.evidence's
    # single-use guarantee for reviewed requests (NULLs are exempt in Postgres, so
    # all un-returned loans coexist). See return_direct_loan for the clean 400.
    # PROTECT, never SET_NULL: attached return evidence is never deleted, and a
    # collector-side SET_NULL would erase the link before the photo-delete trigger ran.
    return_evidence = models.OneToOneField(
        "evidence.EvidencePhoto",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    return_notes = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["qr_code"],
                condition=models.Q(status="checked_out"),
                name="uniq_active_public_tool_loan_per_qr",
            ),
            # A physical handover container can only be out on one active loan at a
            # time (NULL containers are excluded by Postgres partial-unique semantics).
            models.UniqueConstraint(
                fields=["container"],
                condition=models.Q(status="checked_out"),
                name="uniq_active_loan_per_container",
            ),
        ]
        indexes = [
            models.Index(fields=["makerspace", "status"]),
            models.Index(fields=["requester", "status"]),
        ]

class PublicProblemReport(models.Model):
    class Outcome(models.TextChoices):
        NO_ISSUE = "no_issue", "No Issue"
        DAMAGED = "damaged", "Damaged"
        MISSING = "missing", "Missing"
        NEEDS_FIX = "needs_fix", "Needs Fix"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.PROTECT,
        related_name="public_problem_reports",
    )
    loan = models.ForeignKey(
        "hardware_requests.PublicToolLoan",
        on_delete=models.PROTECT,
        related_name="problem_reports",
    )
    request = models.ForeignKey(
        "hardware_requests.HardwareRequest",
        on_delete=models.PROTECT,
        related_name="+",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    note = models.TextField()
    outcome = models.CharField(
        max_length=20,
        choices=Outcome.choices,
        blank=True,
        default="",
        db_index=True,
    )
    triage_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        indexes = [models.Index(fields=["makerspace", "resolved_at"])]
