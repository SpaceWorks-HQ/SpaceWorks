"""Member ID cards: a durable, revocable QR credential over one membership.

Design: docs/plans/2026-09-02-codex-plans/ev_artifacts.md §2 (reviewed), built in forward-plan
phase 5. The card is `membership`-module behaviour with no module key of its own; its QR is
a core `qr_management` `QrCode` with target type `member_card`, so revocation, active-target
uniqueness and the immutable scan history are the ones every other QR already has.

Privacy shape: `printed_name` is scoped source PII (encrypted at rest, registered in
`apps/encryption/registry.py`); the photo is a PRIVATE object (`apps/backup/
object_ownership_registry.py`) readable only through short-lived signed GETs. Revocation
deletes the photo bytes and blanks the name immediately (`member_card_services.redact`);
only the redacted row, the revoked QR, the scans and the audit entries remain.
"""
from django.db import models
from django.utils import timezone

from apps.encryption.mappers import ScopedPiiModelMixin


class MemberCard(ScopedPiiModelMixin, models.Model):
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="member_cards"
    )
    # SET_NULL so a redacted card target survives membership deletion and historic
    # immutable scans keep pointing at a row, never at a reused integer.
    membership = models.OneToOneField(
        "makerspaces.MakerspaceMembership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="member_card",
    )
    # Printed on the card; per-makerspace sequence, never the QR payload.
    card_number = models.PositiveIntegerField()
    printed_name = models.TextField(blank=True, default="")
    photo_object_key = models.CharField(max_length=300, blank=True, default="")
    photo_content_type = models.CharField(max_length=64, blank=True, default="")
    photo_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    photo_consent_at = models.DateTimeField(null=True, blank=True)
    photo_consent_version = models.CharField(max_length=32, blank=True, default="")
    template_version_at_issue = models.PositiveIntegerField(default=1)
    print_count = models.PositiveIntegerField(default=0)
    last_printed_at = models.DateTimeField(null=True, blank=True)
    issued_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "card_number"], name="uniq_member_card_number"
            ),
            # Photo fields travel as a set: all present (with consent) or all absent.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        photo_object_key="", photo_content_type="", photo_size_bytes__isnull=True,
                        photo_consent_at__isnull=True, photo_consent_version="",
                    )
                    | models.Q(
                        photo_size_bytes__isnull=False, photo_consent_at__isnull=False,
                    )
                    & ~models.Q(photo_object_key="")
                    & ~models.Q(photo_content_type="")
                    & ~models.Q(photo_consent_version="")
                ),
                name="member_card_photo_all_or_nothing",
            ),
        ]
        indexes = [
            models.Index(fields=["makerspace", "revoked_at"], name="membercard_ms_revoked_idx"),
        ]
        ordering = ["makerspace_id", "card_number"]

    @property
    def is_active(self):
        return self.revoked_at is None and self.membership_id is not None

    def __str__(self):
        return f"card #{self.card_number} ({self.makerspace_id})"
