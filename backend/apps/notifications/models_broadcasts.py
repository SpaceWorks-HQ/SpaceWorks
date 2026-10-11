"""Staff-authored announcements; recipient visibility lives in personal inbox rows."""

from django.conf import settings
from django.db import models
from apps.encryption.mappers import ScopedPiiModelMixin


class MemberBroadcast(ScopedPiiModelMixin, models.Model):
    makerspace = models.ForeignKey('makerspaces.Makerspace', on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    title = models.TextField()
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
