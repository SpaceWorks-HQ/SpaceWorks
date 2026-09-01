from django.conf import settings
from django.db import models

from apps.makerspaces.secrets import decrypt_value, encrypt_value


class SocialProvider(models.TextChoices):
    GOOGLE = "google", "Google"
    APPLE = "apple", "Apple"


class SocialSurface(models.TextChoices):
    MEMBER = "member", "Member"
    STAFF = "staff", "Staff"


class SocialDelivery(models.TextChoices):
    WEB = "web", "Web"
    DEVICE = "device", "Device"


class SocialClientPlatform(models.TextChoices):
    WEB = "web", "Web"
    IOS = "ios", "iOS"
    ANDROID = "android", "Android"


class SocialIdentity(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_identities",
    )
    # 64 and no `choices`: a generic OIDC provider is stored as `oidc:<slug>`, which is
    # open-ended by design. Validity is decided by `models_oidc.provider_for_slug`, which
    # answers from configuration -- an enum could never list them.
    provider = models.CharField(max_length=64)
    provider_sub = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_sub"], name="uniq_social_provider_sub"
            ),
            models.UniqueConstraint(
                fields=["user", "provider"], name="uniq_social_user_provider"
            ),
        ]


class SocialLoginNonce(models.Model):
    provider = models.CharField(max_length=64)
    surface = models.CharField(max_length=16, choices=SocialSurface.choices)
    delivery = models.CharField(max_length=16, choices=SocialDelivery.choices)
    client_platform = models.CharField(
        max_length=16, choices=SocialClientPlatform.choices
    )
    nonce_digest = models.CharField(max_length=64, unique=True)
    origin = models.CharField(max_length=512, blank=True, default="")
    device_grant = models.ForeignKey(
        "accounts.DeviceGrant",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="social_login_nonces",
    )
    attestation_challenge = models.ForeignKey(
        "accounts.DeviceAttestationChallenge",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="social_login_nonces",
    )
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["expires_at", "consumed_at"], name="social_nonce_use_idx"
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        delivery=SocialDelivery.WEB,
                        device_grant__isnull=True,
                        attestation_challenge__isnull=True,
                    )
                    | models.Q(
                        delivery=SocialDelivery.DEVICE,
                        device_grant__isnull=False,
                        attestation_challenge__isnull=True,
                    )
                    | models.Q(
                        delivery=SocialDelivery.DEVICE,
                        device_grant__isnull=True,
                        attestation_challenge__isnull=False,
                    )
                ),
                name="social_nonce_delivery_anchor_ck",
            )
        ]


class PlatformSocialAuthSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    google_web_client_id = models.CharField(max_length=255, blank=True, default="")
    google_ios_client_id = models.CharField(max_length=255, blank=True, default="")
    google_android_client_id = models.CharField(max_length=255, blank=True, default="")
    apple_service_id = models.CharField(max_length=255, blank=True, default="")
    apple_native_app_ids = models.JSONField(default=list, blank=True)
    apple_team_id = models.CharField(max_length=64, blank=True, default="")
    apple_key_id = models.CharField(max_length=64, blank=True, default="")
    apple_private_key = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def set_apple_private_key(self, raw):
        self.apple_private_key = encrypt_value(raw) if raw else ""

    def get_apple_private_key(self):
        return decrypt_value(self.apple_private_key) if self.apple_private_key else ""

    @property
    def apple_private_key_set(self):
        return bool(self.apple_private_key)

    def client_id(self, provider, client_platform):
        if provider == SocialProvider.GOOGLE:
            return {
                SocialClientPlatform.WEB: self.google_web_client_id,
                SocialClientPlatform.IOS: self.google_ios_client_id,
                SocialClientPlatform.ANDROID: self.google_android_client_id,
            }.get(client_platform, "")
        if provider == SocialProvider.APPLE:
            if client_platform == SocialClientPlatform.WEB:
                return self.apple_service_id
            return client_platform in {
                SocialClientPlatform.IOS,
                SocialClientPlatform.ANDROID,
            } and next(
                (item for item in self.apple_native_app_ids if isinstance(item, str)),
                "",
            ) or ""
        return ""
