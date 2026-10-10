from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.crypto import get_random_string

from apps.makerspaces.capabilities import default_enabled_features
from apps.makerspaces.module_registry import default_enabled_module_keys
from apps.makerspaces.provenance import validate_actor_snapshot
from apps.makerspaces.request_access import reconcile_enabled_modules
from apps.makerspaces.models_makerspace_secrets import MakerspaceSecretsMixin
from apps.makerspaces.models_makerspace_validation import clean_makerspace
from apps.makerspaces.profile_validation import (
    default_timezone, validate_country, validate_opening_hours, validate_timezone,
)
from apps.makerspaces.reminder_policy import (
    default_reminder_lead_hours, validate_reminder_lead_hours,
)
from apps.makerspaces.validators import (
    validate_presence_presets,
    DEFAULT_PRESENCE_PRESETS,
    validate_google_maps_url,
)
from apps.makerspaces.models import (
    default_branding_config,
    default_enabled_modules,
    default_theme_config,
    generate_domain_verification_token,
    generate_public_code,
    generate_publishable_key,
    normalize_frontend_domain,
)


class Makerspace(MakerspaceSecretsMixin, models.Model):
    class LifecycleState(models.TextChoices):
        ACTIVE = "active", "Active"
        IMPORTING = "importing", "Importing"
        ABORTED = "aborted", "Aborted"

    class MembershipPolicy(models.TextChoices):
        REQUEST = "request", "Request"
        OPEN = "open", "Open"
        INVITE_ONLY = "invite_only", "Invite only"

    class DomainStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"

    class PublicPrintStatusLookupPolicy(models.TextChoices):
        TOKEN_ONLY = "token_only", "Token only"
        EMAIL_UNVERIFIED = "email_unverified", "Email unverified"

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, db_index=True)
    public_code = models.CharField(
        max_length=4,
        unique=True,
        db_index=True,
        default=generate_public_code,
        validators=[
            RegexValidator(
                regex=r"^[A-Z0-9]{4}$",
                message="Public code must be exactly 4 uppercase letters or digits.",
            )
        ],
    )
    location = models.CharField(max_length=200, blank=True)
    timezone = models.CharField(max_length=100, default=default_timezone, validators=[validate_timezone])
    country = models.CharField(max_length=2, blank=True, default="", validators=[validate_country])
    opening_hours = models.JSONField(default=dict, blank=True, validators=[validate_opening_hours])
    map_url = models.URLField(blank=True, default="", validators=[validate_google_maps_url])
    geofence_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    geofence_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    geofence_radius_m = models.PositiveIntegerField(default=25, validators=[MinValueValidator(1)])
    geofence_enabled = models.BooleanField(default=False)
    public_inventory_enabled = models.BooleanField(default=True)
    # Account-less requests are an unauthenticated write surface, so this is an
    # independent opt-in. In particular, it must not follow the membership module:
    # recommended installs omit that module and must stay closed after an upgrade.
    #
    # The reverse direction IS coupled, and `save()` enforces it: installing
    # `membership` forces this off, because the anonymous branch of RequestSubmitView
    # runs before any membership guard and would otherwise walk straight past the
    # requirement the operator just switched on. See `request_access`.
    anonymous_requests_enabled = models.BooleanField(default=False)
    public_stats_enabled = models.BooleanField(default=False)
    public_stats_show_holder_names = models.BooleanField(default=False)
    public_print_status_lookup_policy = models.CharField(
        max_length=32,
        choices=PublicPrintStatusLookupPolicy.choices,
        default=PublicPrintStatusLookupPolicy.TOKEN_ONLY,
    )
    membership_policy = models.CharField(
        max_length=16,
        choices=MembershipPolicy.choices,
        default=MembershipPolicy.REQUEST,
    )
    membership_dues_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    referrals_enabled = models.BooleanField(default=False)
    # Opt-in: a member whose membership terms have all expired or been cancelled is
    # refused a borrow request like a non-member. A member with no term at all is never
    # affected -- plans are optional. Enforced by `request_access.require_current_term`.
    lapsed_members_cannot_borrow = models.BooleanField(default=False)
    # 0 = off. When > 0, active filament spools at/below this remaining weight
    # can auto-create a printing procurement item.
    filament_low_stock_threshold_grams = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    superadmin_access_enabled = models.BooleanField(default=True)
    staff_notifications_enabled = models.BooleanField(default=True)
    booking_requester_notifications_enabled = models.BooleanField(default=False)
    event_reminder_lead_hours = models.JSONField(
        default=default_reminder_lead_hours, blank=True, validators=[validate_reminder_lead_hours],
    )
    booking_reminder_lead_hours = models.JSONField(
        default=default_reminder_lead_hours, blank=True, validators=[validate_reminder_lead_hours],
    )
    logo_key = models.CharField(max_length=300, blank=True, default="")
    cover_image_key = models.CharField(max_length=300, blank=True, default="")
    # Case-insensitive uniqueness is enforced by the Lower() UniqueConstraint in Meta
    # (which also covers exact duplicates); no field-level unique index needed.
    frontend_domain = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
    frontend_domain_status = models.CharField(
        max_length=16,
        choices=DomainStatus.choices,
        default=DomainStatus.PENDING,
    )
    domain_verification_token = models.CharField(
        max_length=64,
        editable=False,
        default=generate_domain_verification_token,
    )
    domain_verified_at = models.DateTimeField(null=True, blank=True)
    frontend_domain_changed_at = models.DateTimeField(null=True, blank=True)
    hidden_from_central_directory = models.BooleanField(default=False)
    public_api_key = models.CharField(
        max_length=40,
        editable=False,
        default=generate_publishable_key,
    )
    cors_allowed_origins = models.JSONField(default=list, blank=True)
    enabled_modules = models.JSONField(default=default_enabled_modules, blank=True)
    enabled_features = models.JSONField(default=default_enabled_features, blank=True)
    resource_limit_overrides = models.JSONField(default=dict, blank=True)
    storage_bytes_used = models.BigIntegerField(default=0)
    theme_config = models.JSONField(default=default_theme_config, blank=True)
    branding_config = models.JSONField(default=default_branding_config, blank=True)
    telegram_group_chat_id = models.CharField(max_length=64, blank=True)
    telegram_bot_token = models.CharField(max_length=200, blank=True)
    smtp_host = models.CharField(max_length=200, blank=True)
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_username = models.CharField(max_length=200, blank=True)
    smtp_password = models.CharField(max_length=200, blank=True)
    smtp_use_tls = models.BooleanField(default=True)
    # Implicit SSL (port 465). Mutually exclusive with STARTTLS (smtp_use_tls):
    # when set, the mail connection ignores use_tls. Lets a makerspace use a
    # 465-only provider (e.g. Gmail implicit SSL) instead of STARTTLS on 587.
    smtp_use_ssl = models.BooleanField(default=False)
    smtp_from_email = models.EmailField(blank=True)
    # Per-makerspace chat webhooks (Slack, Slack-compatible Mattermost, and Discord).
    # Stored as Fernet ciphertext (or "") exactly like telegram_bot_token/smtp_password;
    # TextField avoids truncation after base64 expansion. Never returned by any
    # serializer (write-only + *_set).
    #
    # Per-makerspace by nature, not by override: the tenant owns the destination channel
    # and pays for it. Identity credentials are the opposite case and stay platform-wide.
    slack_webhook_url = models.TextField(blank=True, default="")
    mattermost_webhook_url = models.TextField(blank=True, default="")
    discord_webhook_url = models.TextField(blank=True, default="")
    default_loan_days = models.PositiveIntegerField(default=7)
    presence_preset_minutes = models.JSONField(
        default=list, blank=True, validators=[validate_presence_presets]
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_makerspaces",
    )
    anonymous_requester = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    # Soft-delete state. archived_at IS NOT NULL => archived (single source of truth; no
    # separate boolean). Operational reachability also requires lifecycle_state=ACTIVE;
    # importing/aborted rows stay visible only to narrow import/recovery operations.
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    lifecycle_state = models.CharField(
        max_length=16,
        choices=LifecycleState.choices,
        default=LifecycleState.ACTIVE,
        db_index=True,
    )
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["public_api_key"],
                name="uniq_makerspace_public_api_key",
            ),
            models.UniqueConstraint(
                Lower("frontend_domain"),
                name="uniq_makerspace_frontend_domain_ci",
            ),
            models.CheckConstraint(
                condition=Q(hidden_from_central_directory=False)
                | Q(frontend_domain__isnull=False),
                name="ck_makerspace_hidden_requires_domain",
            ),
            models.CheckConstraint(
                condition=Q(membership_dues_amount__gte=0),
                name="makerspace_dues_nonnegative",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def geofence_effective(self) -> bool:
        return bool(self.geofence_enabled and self.geofence_latitude is not None and self.geofence_longitude is not None)

    def save(self, *args, **kwargs):
        fields = kwargs.get("update_fields")
        sync_loan_policy = bool(self.pk) and (fields is None or "default_loan_days" in fields)
        self.public_code = (self.public_code or "").upper()
        self.frontend_domain = normalize_frontend_domain(self.frontend_domain)
        # Membership and account-less requests are mutually exclusive, and this is the
        # ONE chokepoint every writer passes through: module install/uninstall, profile
        # application, the /control/ capability matrix, setup_instance, seed_demo and a
        # plain obj.save(). Enforcing it here rather than in each of them is what makes
        # the state unreachable instead of merely discouraged -- see
        # `request_access` for why the pair is impossible.
        reconciled = reconcile_enabled_modules(
            self.enabled_modules, self.anonymous_requests_enabled
        )
        if reconciled != self.anonymous_requests_enabled:
            self.anonymous_requests_enabled = reconciled
            # A partial save that did not name this field would otherwise change the
            # attribute in memory and leave the row in the impossible state.
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = [*update_fields, "anonymous_requests_enabled"]
        with transaction.atomic():
            super().save(*args, **kwargs)
            if sync_loan_policy:
                # Keep the maker row lock through the mirror update. Otherwise a
                # concurrent policy edit could commit between these two writes.
                # Never create a policy or opt into the ladder during a legacy edit.
                from .models_loan_policy import MakerspaceLoanPolicy

                MakerspaceLoanPolicy.objects.filter(makerspace=self).update(default_loan_days=self.default_loan_days)

    def clean(self):
        clean_makerspace(self)
