import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.makerspaces.models import Makerspace


def generate_box_code():
    return uuid.uuid4().hex


class Box(models.Model):
    # `code` is a GLOBALLY-unique opaque QR payload (intentional; stricter than per-makerspace).
    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.CASCADE,
        related_name="boxes",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    code = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        default=generate_box_code,
    )
    label = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "label"],
                name="uniq_box_label_per_makerspace",
            ),
        ]

    def __str__(self):
        return f"{self.label} [{self.makerspace.slug}]"

    def clean(self):
        if self.parent_id:
            if self.parent.makerspace_id != self.makerspace_id:
                raise ValidationError(
                    {"parent": "Parent box must be in the same makerspace."}
                )
            seen = set()
            node = self.parent
            while node is not None:
                if node.pk == self.pk or node.pk in seen:
                    raise ValidationError(
                        {"parent": "A box cannot be its own ancestor."}
                    )
                seen.add(node.pk)
                node = node.parent


class BoxScan(models.Model):
    """Immutable record of a physical box QR scan."""

    class Context(models.TextChoices):
        ISSUE = "issue", "Issue"
        RETURN = "return", "Return"

    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.PROTECT,
        related_name="box_scans",
    )
    box = models.ForeignKey(
        Box,
        on_delete=models.PROTECT,
        related_name="scans",
    )
    request = models.ForeignKey(
        "hardware_requests.HardwareRequest",
        null=True,
        # PROTECT (not SET_NULL): the row is immutable (DB trigger rejects UPDATE), so a
        # SET_NULL on parent-request deletion would fail. Append-only scans must outlive —
        # and block deletion of — the request they evidence. null=True still allows scans
        # with no request (future non-request scans).
        on_delete=models.PROTECT,
        related_name="+",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    context = models.CharField(max_length=20, choices=Context.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("BoxScan rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("BoxScan rows are immutable.")


class QrCode(models.Model):
    class TargetType(models.TextChoices):
        BOX = "box", "Box"
        PRODUCT = "product", "Product"
        ASSET = "asset", "Asset"
        # A member ID card (makerspaces.MemberCard). Resolved ONLY through the dedicated
        # member-card resolver, never the generic scanner path.
        MEMBER_CARD = "member_card", "Member card"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.CASCADE,
        related_name="qr_codes",
    )
    payload = models.CharField(max_length=64, unique=True, default=generate_box_code)
    target_type = models.CharField(max_length=20, choices=TargetType.choices)
    target_id = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "target_type", "target_id"],
                condition=models.Q(status="active"),
                name="uniq_active_qr_per_target",
            ),
        ]

    def __str__(self):
        return f"{self.target_type}:{self.target_id} [{self.status}]"


class QrScanEvent(models.Model):
    """Immutable generalized QR scan record for boxes, products, and assets."""

    class Context(models.TextChoices):
        ISSUE = "issue", "Issue"
        RETURN = "return", "Return"
        INVENTORY_CHECK = "inventory_check", "Inventory Check"
        REASSIGNMENT = "reassignment", "Reassignment"
        SCANNER_LOOKUP = "scanner_lookup", "Scanner Lookup"
        MEMBER_LOOKUP = "member_lookup", "Member card lookup"

    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.PROTECT,
        related_name="qr_scan_events",
    )
    qr_code = models.ForeignKey(
        QrCode,
        on_delete=models.PROTECT,
        related_name="scan_events",
    )
    request = models.ForeignKey(
        "hardware_requests.HardwareRequest",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    context = models.CharField(max_length=32, choices=Context.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["makerspace", "qr_code", "-created_at"],
                name="qrscan_ms_qrcode_created_idx",
            ),
            models.Index(
                fields=["makerspace", "context"],
                name="qrscan_ms_context_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("QrScanEvent rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("QrScanEvent rows are immutable.")
