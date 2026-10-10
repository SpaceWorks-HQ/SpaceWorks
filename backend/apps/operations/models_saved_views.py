"""Personal list preferences, never an authorization grant."""

from django.conf import settings
from django.db import models


class SavedView(models.Model):
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    entity = models.CharField(max_length=24)
    state = models.JSONField(default=dict)
    shared = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        indexes = [models.Index(fields=["makerspace", "entity", "owner"], name="savedview_ms_entity_owner")]
