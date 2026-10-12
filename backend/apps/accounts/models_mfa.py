"""Platform credentials and short-lived first-factor proofs; never tenant-portable."""

import uuid

from django.conf import settings
from django.db import models


class UserMFA(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    secret = models.TextField(blank=True)  # Fernet ciphertext only.
    enabled_at = models.DateTimeField(null=True)
    last_step = models.BigIntegerField(default=-1)
    recovery_digests = models.JSONField(default=list)
    version = models.UUIDField(default=uuid.uuid4)


class MFAChallenge(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_digest = models.CharField(max_length=64, unique=True)
    credential_fingerprint = models.CharField(max_length=64)
    auth_generation = models.CharField(max_length=64)
    mfa_version = models.UUIDField()
    context = models.JSONField(default=dict)
    pending_secret = models.TextField(blank=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
