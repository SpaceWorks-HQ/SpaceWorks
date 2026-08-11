from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.crypto import get_random_string

from apps.makerspaces.capabilities import (
    default_enabled_features,
    prune_features,
    validate_capabilities,
)
from apps.makerspaces.module_registry import default_enabled_module_keys
from apps.makerspaces.secrets import decrypt_value, encrypt_value
from apps.makerspaces.validators import (
    DEFAULT_PRESENCE_PRESETS,
    validate_google_maps_url,
    validate_presence_presets,
)


def generate_publishable_key():
    return f"pk_{get_random_string(32)}"


def generate_domain_verification_token():
    return f"dv_{get_random_string(48)}"


def generate_public_code():
    return get_random_string(4, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def normalize_frontend_domain(value):
    """Reduce a pasted domain/URL/origin to a bare lowercase host (or None).

    A staff member may paste `https://alpha.example/admin`; storing that raw would
    make the origin helpers build `https://https://alpha.example`. Extract just the
    host so `frontend_domain` is always a bare hostname.
    """
    raw = (value or "").strip().lower()
    if not raw:
        return None
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    return (parsed.hostname or "") or None


# Derived from the module registry -- kept as a module-level name because the
# /control/ form and several tests import it. Add a module in module_registry.py.
DEFAULT_ENABLED_MODULES = default_enabled_module_keys()


def default_enabled_modules():
    # Referenced by migration 0009 as a JSONField default, so this import path is
    # load-bearing and must keep resolving. Returns a fresh list every call.
    return default_enabled_module_keys()


def default_theme_config():
    return {
        "mode": "light",
        "primary_color": "#2563eb",
        "accent_color": "#16a34a",
        "logo_url": "",
    }


def default_branding_config():
    return {
        "display_name": "",
        "support_email": "",
        "support_url": "",
    }


def presence_presets(makerspace):
    """Configured presence lengths, with an empty configuration using the defaults."""
    return makerspace.presence_preset_minutes or list(DEFAULT_PRESENCE_PRESETS)


class Makerspace(models.Model):
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
    map_url = models.URLField(blank=True, default="", validators=[validate_google_maps_url])
    geofence_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    geofence_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    geofence_radius_m = models.PositiveIntegerField(default=25, validators=[MinValueValidator(1)])
    geofence_enabled = models.BooleanField(default=False)
    public_inventory_enabled = models.BooleanField(default=True)
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
    # Soft-delete state. archived_at IS NOT NULL â‡’ archived (single source of truth; no
    # separate boolean). An archived makerspace is operationally unreachable for everyone
    # (excluded centrally in rbac + public surfaces) but stays visible to the superadmin in
    # the Django /control/ admin so it can be permanently purged.
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
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
        self.public_code = (self.public_code or "").upper()
        self.frontend_domain = normalize_frontend_domain(self.frontend_domain)
        super().save(*args, **kwargs)

    def clean(self):
        if self.presence_preset_minutes:
            validate_presence_presets(self.presence_preset_minutes)
        # Drop features whose module is not in this row's set BEFORE validating. The
        # module set is authoritative — `_canonical_modules` already normalizes rather
        # than rejects (it adds core keys back), and this is the same class of
        # normalization on the other axis.
        #
        # Without it a row can be born invalid and then never saved again: creating a
        # makerspace with a narrow `enabled_modules` still takes the FIELD default for
        # `enabled_features`, which includes the default-on `payments.enabled` and
        # `mobile.push`. Those demand modules the row does not have, so `clean()` raised
        # on every subsequent save — including saves that touched neither field, such as
        # a Space Manager toggling public stats.
        #
        # The user-facing strictness is unaffected: the `/control/` capability matrix and
        # `module_install` call `validate_capabilities` directly before saving, so a
        # conflict the operator actually expressed is still reported there rather than
        # silently cleared.
        kept, _dropped = prune_features(
            self.enabled_features or [], self.enabled_modules or []
        )
        self.enabled_modules, self.enabled_features = validate_capabilities(
            self.enabled_modules or [], kept
        )
        if self.hidden_from_central_directory and not self.frontend_domain:
            raise ValidationError(
                {
                    "hidden_from_central_directory": (
                        "A frontend domain is required to hide a makerspace from the central directory."
                    )
                }
            )
        if self.geofence_enabled and not self.geofence_effective:
            raise ValidationError({"geofence_enabled": "Set both latitude and longitude before enabling the geofence."})

    def set_telegram_bot_token(self, raw):
        self.telegram_bot_token = encrypt_value(raw)

    def get_telegram_bot_token(self):
        return decrypt_value(self.telegram_bot_token)

    def set_smtp_password(self, raw):
        self.smtp_password = encrypt_value(raw)

    def get_smtp_password(self):
        return decrypt_value(self.smtp_password)

    def set_slack_webhook_url(self, raw):
        self.slack_webhook_url = encrypt_value(raw)

    def get_slack_webhook_url(self):
        return decrypt_value(self.slack_webhook_url)

    def set_mattermost_webhook_url(self, raw):
        self.mattermost_webhook_url = encrypt_value(raw)

    def get_mattermost_webhook_url(self):
        return decrypt_value(self.mattermost_webhook_url)

    def set_discord_webhook_url(self, raw):
        self.discord_webhook_url = encrypt_value(raw)

    def get_discord_webhook_url(self):
        return decrypt_value(self.discord_webhook_url)


class MakerspaceMembership(models.Model):
    # Role is per-makerspace: this membership is what grants a user space-manager/guest-admin
    # rights for THIS makerspace. Global User.role stays for superadmin. Enforcement
    # of scoping/suspension is centralized in the Phase 2 RBAC layer, not here.
    class Role(models.TextChoices):
        SPACE_MANAGER = "space_manager", "Space Manager"
        INVENTORY_MANAGER = "inventory_manager", "Inventory Manager"
        PRINT_MANAGER = "print_manager", "Print Manager"
        # Makerspace-wide machine authority: manages assigned machines end-to-end
        # (the machine + usage/cycle + warranty + maintenance). Action set is exactly
        # {MANAGE_MACHINES}; every machine sub-feature already gates on machine access,
        # so no new RBAC action is needed. Delegable by a Space Manager (Part I).
        MACHINE_MANAGER = "machine_manager", "Machine Manager"
        CUSTOM = "custom", "Custom"

    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="makerspace_memberships",
        limit_choices_to={"is_active": True},
    )
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.SPACE_MANAGER)
    assigned_role = models.ForeignKey(
        "makerspaces.MakerspaceRole",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    # Per-makerspace opt-in for staff lifecycle email notifications. Default True keeps
    # existing behavior (every relevant manager is notified); the space manager can turn
    # an individual manager off in Settings without removing their access.
    receives_notifications = models.BooleanField(default=True)
    can_refer = models.BooleanField(default=True)
    can_verify = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_memberships",
    )
    status = models.CharField(
        max_length=16,
        choices=(("active", "Active"), ("revoked", "Revoked")),
        default="active",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="activated_makerspace_memberships",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="revoked_makerspace_memberships",
    )
    revocation_reason = models.TextField(blank=True)
    waiver_accepted_at = models.DateTimeField(null=True, blank=True)
    waiver_version_accepted = models.CharField(max_length=64, null=True, blank=True)
    accepted_waiver = models.ForeignKey(
        "makerspaces.MakerspaceWaiver", null=True, blank=True, on_delete=models.PROTECT,
        related_name="accepted_by_memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "user"],
                name="uniq_makerspace_user",
            ),
            models.CheckConstraint(
                condition=(
                    Q(waiver_accepted_at__isnull=True, waiver_version_accepted__isnull=True,
                      accepted_waiver__isnull=True)
                    | Q(waiver_accepted_at__isnull=False, waiver_version_accepted__isnull=False,
                        accepted_waiver__isnull=False)
                ),
                name="membership_waiver_acceptance_all_or_none",
            ),
        ]

    def clean(self):
        # Block assigning a membership to a deactivated account (covers the User-side
        # inline where user is the parent and limit_choices_to does not apply).
        if self.user_id and not self.user.is_active:
            raise ValidationError("Cannot assign a makerspace to an inactive user.")
        # An assigned custom role must belong to the SAME makerspace as this
        # membership. Defense-in-depth: the RBAC reader also fails closed on a
        # tenant mismatch, and the role-assignment service rejects it at write.
        if (
            self.assigned_role_id
            and self.makerspace_id
            and self.assigned_role.makerspace_id != self.makerspace_id
        ):
            raise ValidationError(
                {"assigned_role": "Role must belong to the same makerspace."}
            )
        if (
            self.accepted_waiver_id and self.makerspace_id
            and self.accepted_waiver.makerspace_id != self.makerspace_id
        ):
            raise ValidationError({"accepted_waiver": "Waiver must belong to the same makerspace."})

    def __str__(self):
        return f"{self.user} @ {self.makerspace.slug} ({self.role})"


class MakerspaceRole(models.Model):
    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.CASCADE,
        related_name="roles",
    )
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80)
    granted_actions = models.JSONField(default=list, blank=True)
    legacy_role = models.CharField(
        max_length=32,
        choices=tuple(
            choice
            for choice in MakerspaceMembership.Role.choices
            if choice[0] != MakerspaceMembership.Role.CUSTOM
        ),
        null=True,
        blank=True,
    )
    is_default = models.BooleanField(default=False)
    is_protected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "makerspace", name="makerspacerole_ci_name_uniq"
            ),
            models.UniqueConstraint(
                Lower("slug"), "makerspace", name="makerspacerole_ci_slug_uniq"
            ),
            models.UniqueConstraint(
                fields=["makerspace", "legacy_role"],
                condition=Q(legacy_role__isnull=False),
                name="makerspacerole_legacy_uniq",
            ),
            models.CheckConstraint(
                condition=Q(is_default=False) | Q(legacy_role__isnull=False) | Q(is_protected=True),
                name="makerspacerole_default_has_legacy",
            ),
        ]
        indexes = [
            GinIndex(fields=["granted_actions"], name="makerspacerole_actions_gin"),
        ]

    def save(self, *args, **kwargs):
        self.name = (self.name or "").strip()
        if not self.name:
            raise ValidationError("Role name cannot be blank.")
        super().save(*args, **kwargs)


class MakerspaceWaiver(models.Model):
    makerspace = models.ForeignKey(Makerspace, on_delete=models.CASCADE, related_name="waivers")
    body = models.TextField()
    version = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_makerspace_waivers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["makerspace", "version"], name="uniq_waiver_version_per_makerspace"),
            models.UniqueConstraint(fields=["makerspace"], condition=Q(is_active=True), name="uniq_active_waiver_per_makerspace"),
        ]
        ordering = ["-created_at", "-id"]


class MembershipRequest(models.Model):
    class Kind(models.TextChoices):
        REQUEST = "request", "Request"
        INVITE = "invite", "Invite"

    class State(models.TextChoices):
        REQUESTED = "requested", "Requested"
        INVITED = "invited", "Invited"
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    makerspace = models.ForeignKey(Makerspace, on_delete=models.CASCADE, related_name="membership_requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="membership_requests")
    invite_email = models.CharField(max_length=254, blank=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    state = models.CharField(max_length=16, choices=State.choices)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="requested_memberships")
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="invited_memberships")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="decided_membership_requests")
    assigned_role = models.ForeignKey("makerspaces.MakerspaceRole", null=True, blank=True, on_delete=models.PROTECT, related_name="membership_requests")
    auto_activate_on_claim = models.BooleanField(default=False)
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["makerspace", "user"], condition=Q(state__in=["requested", "invited"], user__isnull=False), name="uniq_open_membership_request_user"),
            models.UniqueConstraint(fields=["makerspace", "invite_email"], condition=Q(state__in=["requested", "invited"]) & ~Q(invite_email=""), name="uniq_open_membership_request_email"),
        ]
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        self.invite_email = (self.invite_email or "").strip().lower()
        super().save(*args, **kwargs)


class SubdomainRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.CASCADE,
        related_name="subdomain_requests",
    )
    requested_label = models.CharField(max_length=63)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subdomain_requests",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="decided_subdomain_requests",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace"],
                condition=Q(status="pending"),
                name="uniq_pending_subdomain_request",
            ),
        ]
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.requested_label = (self.requested_label or "").strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.requested_label} ({self.status})"


from apps.makerspaces.models_profiles import (  # noqa: E402,F401
    MemberProfile,
    MemberProject,
)
