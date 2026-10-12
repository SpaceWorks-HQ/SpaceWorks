from django.conf import settings
from django.db import models


class ReturnEvent(models.Model):
    """Immutable record of a physical return event."""

    request = models.ForeignKey(
        "hardware_requests.HardwareRequest",
        on_delete=models.PROTECT,
    )
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.PROTECT,
    )
    box = models.ForeignKey(
        "boxes.Box",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    evidence = models.OneToOneField(
        "evidence.EvidencePhoto",
        on_delete=models.PROTECT,
        related_name="return_event",
    )
    remark = models.TextField()
    kit_checklist = models.JSONField(default=list, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("ReturnEvent rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("ReturnEvent rows are immutable.")


class RequesterAccountability(models.Model):
    """Immutable record of requester damage or loss accountability."""

    class IssueType(models.TextChoices):
        DAMAGED = "damaged", "Damaged"
        MISSING = "missing", "Missing"

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="accountability_records",
    )
    request = models.ForeignKey(
        "hardware_requests.HardwareRequest",
        on_delete=models.PROTECT,
    )
    request_item = models.ForeignKey(
        "hardware_requests.HardwareRequestItem",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.PROTECT,
    )
    issue_type = models.CharField(max_length=20, choices=IssueType.choices)
    description = models.TextField(blank=True)
    evidence_photo = models.ForeignKey(
        "evidence.EvidencePhoto",
        null=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    quantity = models.PositiveIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("RequesterAccountability rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("RequesterAccountability rows are immutable.")
