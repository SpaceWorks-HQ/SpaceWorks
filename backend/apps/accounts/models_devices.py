import uuid

from django.conf import settings
from django.db import models


class DevicePlatform(models.TextChoices):
    APPLE = 'apple', 'Apple'
    ANDROID = 'android', 'Android'


class DeviceEnvironment(models.TextChoices):
    DEVELOPMENT = 'development', 'Development'
    PRODUCTION = 'production', 'Production'


class NativeAppRegistration(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REVOKED = 'revoked', 'Revoked'

    makerspace = models.ForeignKey(
        'makerspaces.Makerspace',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='native_app_registrations',
    )
    app_id = models.CharField(max_length=255)
    platform = models.CharField(max_length=16, choices=DevicePlatform.choices)
    environment = models.CharField(max_length=16, choices=DeviceEnvironment.choices)
    # Indirection keeps verifier credentials in deployment configuration while the
    # database row remains the independently approvable and revocable authority.
    verifier_config_key = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='approved_native_app_registrations',
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['makerspace', 'app_id', 'platform', 'environment'],
                nulls_distinct=False,
                name='uniq_native_app_registration_scope',
            )
        ]
        indexes = [
            models.Index(
                fields=['platform', 'app_id', 'environment', 'status'],
                name='native_app_lookup_idx',
            )
        ]

    def __str__(self):
        scope = self.makerspace_id or 'global'
        return f'{self.app_id} ({self.platform}/{self.environment}, {scope})'


class DeviceAttestationChallenge(models.Model):
    registration = models.ForeignKey(
        NativeAppRegistration,
        on_delete=models.PROTECT,
        related_name='attestation_challenges',
    )
    platform = models.CharField(max_length=16, choices=DevicePlatform.choices)
    app_id = models.CharField(max_length=255)
    signing_identity = models.CharField(max_length=255)
    environment = models.CharField(max_length=16, choices=DeviceEnvironment.choices)
    challenge_digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['expires_at', 'consumed_at'], name='device_challenge_use_idx')]


class DeviceGrant(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        REVOKED = 'revoked', 'Revoked'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    registration = models.ForeignKey(
        NativeAppRegistration,
        on_delete=models.PROTECT,
        related_name='device_grants',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='device_grants',
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    platform = models.CharField(max_length=16, choices=DevicePlatform.choices)
    app_id = models.CharField(max_length=255)
    signing_identity = models.CharField(max_length=255)
    environment = models.CharField(max_length=16, choices=DeviceEnvironment.choices)
    attestation_subject_fingerprint = models.CharField(max_length=64)
    attested_at = models.DateTimeField()
    last_used_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'status'], name='device_grant_user_idx')]


class DeviceRefreshFamily(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grant = models.ForeignKey(
        DeviceGrant,
        on_delete=models.CASCADE,
        related_name='refresh_families',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='device_refresh_families',
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    reuse_detected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['grant', 'revoked_at'], name='device_family_grant_idx')]


class DeviceRefreshToken(models.Model):
    family = models.ForeignKey(
        DeviceRefreshFamily,
        on_delete=models.CASCADE,
        related_name='tokens',
    )
    jti = models.CharField(max_length=255, unique=True)
    token_fingerprint = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    rotated_at = models.DateTimeField(null=True, blank=True)
    blacklisted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['family', 'rotated_at'], name='device_refresh_family_idx')]
