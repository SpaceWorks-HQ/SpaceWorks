from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.makerspaces.models_makerspace import Makerspace
from apps.makerspaces.models_memberships import MakerspaceMembership


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
