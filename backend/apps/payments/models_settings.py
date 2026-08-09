from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

from apps.makerspaces.secrets import decrypt_value, encrypt_value


currency_validator = RegexValidator(
    regex=r"^[a-z]{3}$",
    message="Default currency must be a three-letter lowercase ISO currency code.",
)
connect_account_validator = RegexValidator(
    regex=r"^acct_[A-Za-z0-9]+$",
    message="Enter a valid Stripe connected account ID.",
)


class MakerspacePaymentSettings(models.Model):
    class ConnectStatus(models.TextChoices):
        UNCONNECTED = "unconnected", "Unconnected"
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        RESTRICTED = "restricted", "Restricted"
        DISCONNECTED = "disconnected", "Disconnected"

    makerspace = models.OneToOneField(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="payment_settings"
    )
    # Which vendor this makerspace charges through. Per-makerspace rather than global:
    # a managed deployment can host an Indian space on Razorpay and a US one on Stripe,
    # and a self-hoster in a country Stripe does not serve must not be blocked by a
    # platform-wide choice.
    provider = models.CharField(
        max_length=16,
        choices=[("stripe", "Stripe"), ("razorpay", "Razorpay")],
        default="stripe",
    )
    stripe_publishable_key = models.CharField(max_length=255, blank=True, default="")
    stripe_secret_key = models.TextField(blank=True, default="")
    stripe_webhook_secret = models.TextField(blank=True, default="")
    default_currency = models.CharField(
        max_length=3, default="usd", validators=[currency_validator]
    )
    connect_account_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        validators=[connect_account_validator],
    )
    connect_status = models.CharField(
        max_length=16, choices=ConnectStatus.choices, default=ConnectStatus.UNCONNECTED
    )
    connect_charges_enabled = models.BooleanField(default=False)
    connect_payouts_enabled = models.BooleanField(default=False)
    connect_account_assigned_at = models.DateTimeField(null=True, blank=True)
    connect_status_updated_at = models.DateTimeField(default=timezone.now)
    # Razorpay. `key_id` is public (it appears in the checkout page URL), so it is
    # stored plainly like `stripe_publishable_key`; the other two are encrypted with
    # API_CLIENT_ENC_KEY through the same `secrets` helpers as their Stripe twins.
    razorpay_key_id = models.CharField(max_length=255, blank=True, default="")
    razorpay_key_secret = models.TextField(blank=True, default="")
    razorpay_webhook_secret = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "makerspace payment settings"
        verbose_name_plural = "makerspace payment settings"

    def __str__(self):
        return f"Payments: {self.makerspace}"

    @classmethod
    def for_makerspace(cls, makerspace):
        return cls.objects.filter(makerspace=makerspace).first() or cls(makerspace=makerspace)

    @property
    def raw_credentials_configured(self):
        """Whether the SELECTED provider holds every credential it needs.

        Provider-aware: a space that has switched to Razorpay but still has old Stripe
        keys on the row must not read as configured, or `online_payments_enabled` would
        let it raise a checkout against a vendor it no longer uses.
        """
        if self.provider == "razorpay":
            return bool(
                self.razorpay_key_id
                and self.razorpay_key_secret
                and self.razorpay_webhook_secret
            )
        return bool(self.stripe_secret_key and self.stripe_webhook_secret)

    @property
    def razorpay_key_secret_set(self):
        return bool(self.razorpay_key_secret)

    @property
    def razorpay_webhook_secret_set(self):
        return bool(self.razorpay_webhook_secret)

    def set_razorpay_key_secret(self, raw):
        self.razorpay_key_secret = encrypt_value(raw)

    def get_razorpay_key_secret(self):
        return decrypt_value(self.razorpay_key_secret)

    def set_razorpay_webhook_secret(self, raw):
        self.razorpay_webhook_secret = encrypt_value(raw)

    def get_razorpay_webhook_secret(self):
        return decrypt_value(self.razorpay_webhook_secret)

    @property
    def stripe_secret_key_set(self):
        return bool(self.stripe_secret_key)

    @property
    def stripe_publishable_key_set(self):
        return bool(self.stripe_publishable_key)

    @property
    def stripe_webhook_secret_set(self):
        return bool(self.stripe_webhook_secret)

    @property
    def is_configured(self):
        from apps.payments.resolution import resolve_payment_source

        return self.raw_credentials_configured or resolve_payment_source(self.makerspace) is not None

    def clean(self):
        self.default_currency = (self.default_currency or "").strip().lower()
        try:
            currency_validator(self.default_currency)
        except ValidationError:
            raise ValidationError(
                {"default_currency": "Enter a three-letter lowercase currency code."}
            )

    def save(self, *args, **kwargs):
        self.default_currency = (self.default_currency or "").strip().lower()
        account_changed = False
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values(
                "connect_account_id",
                "connect_status",
                "connect_charges_enabled",
                "connect_payouts_enabled",
            ).first()
            account_changed = bool(
                previous
                and previous["connect_account_id"] != self.connect_account_id
            )
            if previous and any(
                previous[field] != getattr(self, field)
                for field in (
                    "connect_status",
                    "connect_charges_enabled",
                    "connect_payouts_enabled",
                )
            ):
                self.connect_status_updated_at = timezone.now()
                update_fields = kwargs.get("update_fields")
                if update_fields is not None:
                    kwargs["update_fields"] = set(update_fields) | {"connect_status_updated_at"}
        elif self.connect_account_id:
            account_changed = True
        if account_changed:
            self.connect_account_assigned_at = (
                timezone.now() if self.connect_account_id else None
            )
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {
                    "connect_account_assigned_at"
                }
        self.full_clean()
        return super().save(*args, **kwargs)

    def set_stripe_secret_key(self, raw):
        self.stripe_secret_key = encrypt_value(raw)

    def get_stripe_secret_key(self):
        return decrypt_value(self.stripe_secret_key)

    def set_stripe_webhook_secret(self, raw):
        self.stripe_webhook_secret = encrypt_value(raw)

    def get_stripe_webhook_secret(self):
        return decrypt_value(self.stripe_webhook_secret)


class PlatformStripeConnectSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    stripe_publishable_key = models.CharField(max_length=255, blank=True, default="")
    stripe_secret_key = models.TextField(blank=True, default="")
    stripe_webhook_secret = models.TextField(blank=True, default="")
    stripe_connect_client_id = models.CharField(max_length=255, blank=True, default="")
    application_fee_bps = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(10000)]
    )
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def is_configured(self):
        return bool(self.stripe_secret_key and self.stripe_webhook_secret and self.stripe_connect_client_id)

    @property
    def stripe_secret_key_set(self):
        return bool(self.stripe_secret_key)

    @property
    def stripe_publishable_key_set(self):
        return bool(self.stripe_publishable_key)

    @property
    def stripe_webhook_secret_set(self):
        return bool(self.stripe_webhook_secret)

    def set_stripe_secret_key(self, raw):
        self.stripe_secret_key = encrypt_value(raw)

    def get_stripe_secret_key(self):
        return decrypt_value(self.stripe_secret_key)

    def set_stripe_webhook_secret(self, raw):
        self.stripe_webhook_secret = encrypt_value(raw)

    def get_stripe_webhook_secret(self):
        return decrypt_value(self.stripe_webhook_secret)


class StripeConnectOAuthState(models.Model):
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="stripe_connect_oauth_states"
    )
    initiated_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    state_digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
