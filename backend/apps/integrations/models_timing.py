"""Local delivery windows and a write-only, encrypted inbound signing credential."""

from datetime import time

from django.db import models

from apps.makerspaces.secrets import encrypt_value, decrypt_value


class NotificationTimingPolicy(models.Model):
    makerspace = models.OneToOneField('makerspaces.Makerspace', on_delete=models.CASCADE)
    quiet_start = models.TimeField(default=time(22))
    quiet_end = models.TimeField(default=time(8))
    channels = models.JSONField(default=list)
    digest_at = models.TimeField(default=time(8))
    bounce_secret = models.TextField(blank=True)

    def set_bounce_secret(self, value):
        self.bounce_secret = encrypt_value(value) if value else ''

    def get_bounce_secret(self):
        return decrypt_value(self.bounce_secret) if self.bounce_secret else ''
