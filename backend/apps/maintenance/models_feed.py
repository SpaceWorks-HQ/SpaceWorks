from django.conf import settings
from django.db import models


class MaintenanceCalendarFeed(models.Model):
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_digest = models.BinaryField(max_length=32, unique=True)
    token_hint = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["makerspace", "user"],
                                                name="maintenance_feed_tenant_user_unique")]
