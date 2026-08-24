from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.makerspaces.models_makerspace import Makerspace
from apps.makerspaces.provenance import validate_actor_snapshot


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
    verified_actor_snapshot = models.JSONField(
        null=True, blank=True, validators=[validate_actor_snapshot]
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
    activated_actor_snapshot = models.JSONField(
        null=True, blank=True, validators=[validate_actor_snapshot]
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="revoked_makerspace_memberships",
    )
    revoked_actor_snapshot = models.JSONField(
        null=True, blank=True, validators=[validate_actor_snapshot]
    )
    revocation_reason = models.TextField(blank=True)
    waiver_accepted_at = models.DateTimeField(null=True, blank=True)
    waiver_version_accepted = models.CharField(max_length=64, null=True, blank=True)
    accepted_waiver = models.ForeignKey(
        "makerspaces.MakerspaceWaiver", null=True, blank=True, on_delete=models.PROTECT,
        related_name="accepted_by_memberships",
    )
    witnessed_waiver = models.ForeignKey(
        "makerspaces.MakerspaceWaiver", null=True, blank=True, on_delete=models.PROTECT,
        related_name="witnessed_by_memberships",
    )
    witnessed_waiver_version = models.CharField(max_length=64, null=True, blank=True)
    witnessed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="witnessed_waiver_acceptances",
    )
    witnessed_actor_snapshot = models.JSONField(null=True, blank=True)
    witnessed_at = models.DateTimeField(null=True, blank=True)
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
            models.CheckConstraint(
                condition=(
                    Q(
                        witnessed_waiver__isnull=True,
                        witnessed_waiver_version__isnull=True,
                        witnessed_by__isnull=True,
                        witnessed_actor_snapshot__isnull=True,
                        witnessed_at__isnull=True,
                    )
                    | Q(
                        witnessed_waiver__isnull=False,
                        witnessed_waiver_version__isnull=False,
                        witnessed_at__isnull=False,
                    )
                    & (
                        Q(witnessed_by__isnull=False)
                        | Q(witnessed_actor_snapshot__isnull=False)
                    )
                ),
                name="membership_witnessed_waiver_all_or_none",
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
        if (
            self.witnessed_waiver_id and self.makerspace_id
            and self.witnessed_waiver.makerspace_id != self.makerspace_id
        ):
            raise ValidationError(
                {"witnessed_waiver": "Waiver must belong to the same makerspace."}
            )

    def __str__(self):
        return f"{self.user} @ {self.makerspace.slug} ({self.role})"
