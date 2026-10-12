"""Calendar capability owned by an account, so bookings-only spaces need no membership."""

from django.conf import settings
from django.db import models


class BookingCalendarFeed(models.Model):
    makerspace = models.ForeignKey('makerspaces.Makerspace', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_digest = models.BinaryField(max_length=32, unique=True)
    token_hint = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)
    rotated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['makerspace', 'user'], name='uniq_booking_calendar_owner')]
