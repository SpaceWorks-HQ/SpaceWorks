"""Platform SMS credentials and the auth/OTP send counter.

Platform-scoped by necessity, not convenience: phone login resolves before any
makerspace is selected, so there is no tenant context at send time and no tenant
to bill. Mirrors PlatformEmailSettings -- singleton at pk=1, secret encrypted at
rest, editable only from /control/.
"""

from django.db import models

from apps.makerspaces.secrets import decrypt_value, encrypt_value


class SmsProviderChoice(models.TextChoices):
    TWILIO = "twilio", "Twilio"


class PlatformSmsSettings(models.Model):
    # A master switch separate from credential presence, so an operator can cut SMS
    # without destroying the credentials they would have to re-enter to restore it.
    is_enabled = models.BooleanField(default=False)
    provider = models.CharField(
        max_length=32,
        choices=SmsProviderChoice.choices,
        default=SmsProviderChoice.TWILIO,
    )
    account_sid = models.CharField(max_length=255, blank=True)
    auth_token = models.CharField(max_length=512, blank=True)
    from_number = models.CharField(max_length=32, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def set_auth_token(self, raw):
        self.auth_token = encrypt_value(raw) if raw else ""

    def get_auth_token(self):
        return decrypt_value(self.auth_token) if self.auth_token else ""

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Platform SMS settings"


class DailyOtpSmsCounter(models.Model):
    """Platform-wide daily cap on auth OTP texts.

    SMS costs real money per message, so an unthrottled OTP endpoint is a way to
    spend an operator's balance as well as a way to spam a stranger's handset. The
    twin of DailyOtpEmailCounter.
    """

    day = models.DateField(unique=True)
    count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.day}: {self.count}"
