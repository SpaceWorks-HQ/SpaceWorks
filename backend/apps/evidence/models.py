from django.conf import settings
from django.db import models


class EvidencePhoto(models.Model):
    """Immutable evidence object record; database triggers are the real guard."""

    class EvidenceType(models.TextChoices):
        ISSUE = "issue", "Issue"
        RETURN = "return", "Return"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.PROTECT,
        related_name="evidence_photos",
    )
    evidence_type = models.CharField(max_length=20, choices=EvidenceType.choices)
    object_key = models.CharField(max_length=512, unique=True)
    content_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("EvidencePhoto rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("EvidencePhoto rows are immutable.")

    def __str__(self):
        return f"{self.evidence_type} evidence {self.pk}"


class EvidenceUploadFinalization(models.Model):
    """Mutable coordination state kept separate from immutable evidence metadata."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROMOTING = "promoting", "Promoting"
        FINALIZED = "finalized", "Finalized"

    evidence = models.OneToOneField(
        EvidencePhoto,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="upload_finalization",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    claim_token = models.UUIDField(null=True, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=128, blank=True)
    quota_charged = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
