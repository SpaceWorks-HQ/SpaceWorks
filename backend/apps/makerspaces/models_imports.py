from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.makerspaces.provenance import validate_actor_snapshot


class ImportedUserReconciliation(models.Model):
    """Persist an operator's explicit source-person to target-account decision.

    "A target account exists" means any target User row occupying the email
    case-insensitively, including a walk-in. "Operator reconciliation" means this
    explicit persisted input naming the archived person and target account, never
    an unstored human judgement.
    """

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="imported_user_reconciliations",
    )
    source_user_id = models.CharField(max_length=255)
    source_username = models.CharField(max_length=255)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="imported_identity_reconciliations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "source_user_id"],
                name="uniq_import_reconciliation_source_user",
            ),
            models.CheckConstraint(
                condition=~Q(source_user_id=""),
                name="import_reconciliation_source_user_present",
            ),
        ]


class PendingImportedMembership(models.Model):
    """Lossless imported membership state awaiting proof of its email address."""

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="pending_imported_memberships",
    )
    email = models.EmailField()
    archived_role_label = models.CharField(max_length=255, blank=True)
    receives_notifications = models.BooleanField(default=True)
    can_refer = models.BooleanField(default=True)
    can_verify = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_actor_snapshot = models.JSONField(
        null=True, blank=True, validators=[validate_actor_snapshot]
    )
    status = models.CharField(
        max_length=16,
        choices=(("active", "Active"), ("revoked", "Revoked")),
        default="active",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_actor_snapshot = models.JSONField(
        null=True, blank=True, validators=[validate_actor_snapshot]
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_actor_snapshot = models.JSONField(
        null=True, blank=True, validators=[validate_actor_snapshot]
    )
    revocation_reason = models.TextField(blank=True)
    waiver_accepted_at = models.DateTimeField(null=True, blank=True)
    waiver_version_accepted = models.CharField(max_length=64, null=True, blank=True)
    accepted_waiver = models.ForeignKey(
        "makerspaces.MakerspaceWaiver",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="pending_imported_acceptances",
    )
    witnessed_waiver = models.ForeignKey(
        "makerspaces.MakerspaceWaiver",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="pending_imported_witnessed_acceptances",
    )
    witnessed_waiver_version = models.CharField(max_length=64, null=True, blank=True)
    witnessed_actor_snapshot = models.JSONField(
        null=True, blank=True, validators=[validate_actor_snapshot]
    )
    witnessed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()
    source_membership_id = models.CharField(max_length=255)
    adopted_at = models.DateTimeField(null=True, blank=True)
    adopted_membership = models.OneToOneField(
        "makerspaces.MakerspaceMembership",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="import_adoption",
    )
    unresolved_reason = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                "makerspace", Lower("email"), name="uniq_pending_import_email_ci"
            ),
            models.UniqueConstraint(
                fields=["makerspace", "source_membership_id"],
                name="uniq_pending_import_source_membership",
            ),
            models.CheckConstraint(
                condition=~Q(email="") & ~Q(source_membership_id=""),
                name="pending_import_identity_present",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        waiver_accepted_at__isnull=True,
                        waiver_version_accepted__isnull=True,
                        accepted_waiver__isnull=True,
                    )
                    | Q(
                        waiver_accepted_at__isnull=False,
                        waiver_version_accepted__isnull=False,
                        accepted_waiver__isnull=False,
                    )
                ),
                name="pending_import_self_waiver_all_or_none",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        witnessed_waiver__isnull=True,
                        witnessed_waiver_version__isnull=True,
                        witnessed_actor_snapshot__isnull=True,
                        witnessed_at__isnull=True,
                    )
                    | Q(
                        witnessed_waiver__isnull=False,
                        witnessed_waiver_version__isnull=False,
                        witnessed_actor_snapshot__isnull=False,
                        witnessed_at__isnull=False,
                    )
                ),
                name="pending_import_witnessed_waiver_all_or_none",
            ),
            models.CheckConstraint(
                condition=(
                    Q(adopted_at__isnull=True, adopted_membership__isnull=True)
                    | Q(
                        adopted_at__isnull=False,
                        adopted_membership__isnull=False,
                        unresolved_reason="",
                    )
                ),
                name="pending_import_terminal_state_consistent",
            ),
        ]

    def clean(self):
        for field in ("accepted_waiver", "witnessed_waiver"):
            waiver = getattr(self, field, None)
            if waiver and waiver.makerspace_id != self.makerspace_id:
                raise ValidationError({field: "Waiver must belong to the makerspace."})
