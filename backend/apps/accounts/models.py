from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


def _normalized_email(value):
    return (value or "").strip().lower()


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPERADMIN = "superadmin", "Super Admin"
        SPACE_MANAGER = "space_manager", "Space Manager"
        REQUESTER = "requester", "Requester"

    class AccessStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        RESTRICTED = "restricted", "Restricted"
        SUSPENDED = "suspended", "Suspended"

    # Free-text contact info, copied onto requests/bookings as text. Stays exactly as
    # the user typed it, non-unique: two members may legitimately share a landline.
    phone = models.CharField(max_length=32, blank=True)
    # The LOGIN IDENTITY -- a separate, canonical E.164 column, deliberately not the
    # same field. Reusing `phone` would have meant rewriting existing free-text values
    # in a migration and putting a unique index on a column that already holds
    # duplicates in real deployments. This one starts empty everywhere, so its
    # constraint always applies cleanly.
    phone_e164 = models.CharField(max_length=20, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    external_checkin_user_id = models.CharField(max_length=128, blank=True)
    telegram_user_id = models.CharField(max_length=64, blank=True)
    must_change_password = models.BooleanField(default=False)
    role = models.CharField(
        max_length=32,
        choices=Role.choices,
        default=Role.REQUESTER,
    )
    access_status = models.CharField(
        max_length=32,
        choices=AccessStatus.choices,
        default=AccessStatus.ACTIVE,
    )
    restriction_reason = models.TextField(blank=True)

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["external_checkin_user_id"],
                condition=~models.Q(external_checkin_user_id=""),
                name="uniq_external_checkin_user_id",
            ),
            models.UniqueConstraint(
                fields=["telegram_user_id"],
                condition=~models.Q(telegram_user_id=""),
                name="uniq_telegram_user_id",
            ),
            models.UniqueConstraint(
                Lower("email"),
                condition=~models.Q(email=""),
                name="uniq_ci_nonempty_email",
            ),
            models.UniqueConstraint(
                fields=["phone_e164"],
                condition=~models.Q(phone_e164=""),
                name="uniq_nonempty_phone_e164",
            ),
        ]

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_email = instance.email
        instance._loaded_phone_e164 = instance.phone_e164
        return instance

    def save(self, *args, **kwargs):
        # Changing a verified email must re-require verification: an admin/self email
        # edit clears email_verified_at (outstanding challenges reference the old email
        # snapshot and can no longer match the new current email, so they lapse).
        cleared = []
        if getattr(self, "_loaded_email", None) is not None and _normalized_email(
            self._loaded_email
        ) != _normalized_email(self.email):
            self.email_verified_at = None
            cleared.append("email_verified_at")
        # The same rule for the phone identity, and it matters more here: phone_e164 is
        # what the OTP login resolves an account by, so an edited number that kept its
        # verified stamp would let whoever holds the NEW number sign in as this user
        # without ever proving they hold it. /control/ can edit this field, so the guard
        # cannot live only in the linking service.
        if getattr(
            self, "_loaded_phone_e164", None
        ) is not None and self._loaded_phone_e164 != self.phone_e164:
            self.phone_verified_at = None
            cleared.append("phone_verified_at")
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and cleared:
            kwargs["update_fields"] = list(update_fields) + [
                name for name in cleared if name not in update_fields
            ]
        super().save(*args, **kwargs)
        self._loaded_email = self.email
        self._loaded_phone_e164 = self.phone_e164


class EmailVerificationChallenge(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="email_challenges"
    )
    email = models.CharField(max_length=254)
    code_digest = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "email", "expires_at"]),
            models.Index(
                fields=["user", "email"],
                condition=models.Q(consumed_at__isnull=True),
                name="email_challenge_active_idx",
            ),
        ]

    def is_usable(self, now):
        return (
            self.consumed_at is None
            and self.failed_attempts < 5
            and self.expires_at > now
        )


class DailyOtpEmailCounter(models.Model):
    day = models.DateField(unique=True)
    count = models.PositiveIntegerField(default=0)


from apps.accounts.models_devices import (  # noqa: E402
    DeviceAttestationChallenge,
    DeviceEnvironment,
    DeviceGrant,
    DevicePlatform,
    DeviceRefreshFamily,
    DeviceRefreshToken,
)
from apps.accounts.models_login_methods import PlatformLoginMethods  # noqa: E402
from apps.accounts.models_phone import (  # noqa: E402
    PhoneChallengePurpose,
    PhoneVerificationChallenge,
)
from apps.accounts.models_social import (  # noqa: E402
    PlatformSocialAuthSettings,
    SocialClientPlatform,
    SocialDelivery,
    SocialIdentity,
    SocialLoginNonce,
    SocialProvider,
    SocialSurface,
)

__all__ = [
    'DailyOtpEmailCounter',
    'DeviceAttestationChallenge',
    'DeviceEnvironment',
    'DeviceGrant',
    'DevicePlatform',
    'DeviceRefreshFamily',
    'DeviceRefreshToken',
    'EmailVerificationChallenge',
    'PhoneChallengePurpose',
    'PhoneVerificationChallenge',
    'PlatformLoginMethods',
    'PlatformSocialAuthSettings',
    'SocialClientPlatform',
    'SocialDelivery',
    'SocialIdentity',
    'SocialLoginNonce',
    'SocialProvider',
    'SocialSurface',
    'User',
]
