from django.conf import settings
from django.db import models
from django.db.models import Q


class MakerspaceArchiveRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Declined"
        WITHDRAWN = "withdrawn", "Withdrawn"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="archive_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="makerspace_archive_requests",
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_makerspace_archive_requests",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(
        max_length=2000,
        help_text="Do not include personal data. Maximum 2,000 characters.",
    )
    resolution_note = models.TextField(blank=True, max_length=2000)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )

    class Meta:
        ordering = ["-requested_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace"],
                condition=Q(status="pending"),
                name="uniq_pending_makerspace_archive_request",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="pending",
                        resolved_at__isnull=True,
                        resolved_by__isnull=True,
                    )
                    | Q(
                        status__in=["approved", "declined", "withdrawn"],
                        resolved_at__isnull=False,
                    )
                ),
                name="ck_archive_request_resolution_state",
            ),
            models.CheckConstraint(
                condition=~Q(status="declined") | ~Q(resolution_note=""),
                name="ck_declined_archive_request_has_note",
            ),
            models.CheckConstraint(
                condition=~Q(reason=""),
                name="ck_archive_request_has_reason",
            ),
        ]

    def __str__(self):
        return f"{self.makerspace} ({self.status})"
