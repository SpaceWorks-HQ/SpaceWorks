from django.db import models


class MemberCalendarFeed(models.Model):
    """Deployment-local bearer credential for one membership's event feed.

    Only the SHA-256 digest is persisted. The raw 256-bit token is returned once when
    created or rotated and never enters tenant exports or audit metadata.
    """

    membership = models.OneToOneField(
        "makerspaces.MakerspaceMembership",
        on_delete=models.CASCADE,
        related_name="event_calendar_feed",
    )
    token_digest = models.BinaryField(max_length=32, unique=True)
    token_hint = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)
    rotated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("membership_id",)
