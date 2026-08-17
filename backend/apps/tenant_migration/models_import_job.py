import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class TenantImportJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        AWAITING_IDENTITY = "awaiting_identity", "Awaiting identity decisions"
        READY = "ready", "Ready"
        MATERIALIZING = "materializing", "Materializing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        ABANDONED = "abandoned", "Abandoned"

    TERMINAL_STATUSES = frozenset({Status.COMPLETED, Status.FAILED, Status.ABANDONED})

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_archive_digest = models.CharField(max_length=64)
    source_makerspace_id = models.CharField(max_length=64, blank=True)
    source_makerspace_slug = models.CharField(max_length=100, blank=True)
    source_makerspace_name = models.CharField(max_length=200, blank=True)
    source_deployment_id = models.CharField(max_length=128, blank=True)
    source_deployment_identity = models.JSONField(default=dict, blank=True)
    storage_mode = models.CharField(max_length=32, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tenant_import_jobs",
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    # SET_NULL is deliberate: PROTECT would make tenant purge impossible. CASCADE would
    # not solve the wider lifecycle either, because failed/abandoned pre-tenant jobs have
    # no makerspace FK and would still retain attacker-supplied identity data forever.
    target_makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tenant_import_jobs",
    )
    aggregate_outcome = models.JSONField(default=dict, blank=True)
    archive_path = models.CharField(max_length=1024, blank=True)
    verification_report = models.JSONField(default=dict, blank=True)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_detail = models.CharField(max_length=500, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    terminal_at = models.DateTimeField(null=True, blank=True)
    scrubbed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("target_makerspace", "status", "expires_at"),
                name="timport_target_status_exp_idx",
            )
        ]


class ImportIdentityDecision(models.Model):
    class IdentityResolution(models.TextChoices):
        LINK_EXISTING = "link_existing", "Link existing account"
        CREATE_WALK_IN = "create_walk_in", "Create walk-in account"

    class MembershipDisposition(models.TextChoices):
        IMPORT_MEMBERSHIP = "import_membership", "Import membership"
        NO_MEMBERSHIP = "no_membership", "Do not import membership"

    job = models.ForeignKey(
        TenantImportJob, on_delete=models.CASCADE, related_name="identity_decisions"
    )
    source_user_id = models.CharField(max_length=255)
    source_email = models.EmailField(null=True, blank=True)
    identity_resolution = models.CharField(
        max_length=24, choices=IdentityResolution.choices
    )
    membership_disposition = models.CharField(
        max_length=24, choices=MembershipDisposition.choices
    )
    # These axes cannot be collapsed: declining membership does not dispose of a
    # person. Retained rows have non-null attribution through
    # evidence.EvidencePhoto.uploaded_by, boxes.BoxScan.actor,
    # hardware_requests.HardwareRequest.requester, payments.Payment.created_by,
    # machines.MachineServiceRequest.requester,
    # hardware_requests.RequesterAccountability.requester, and the raw non-null
    # machines.ServiceRequestFile.owner_user_id.
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tenant_import_identity_decisions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("job", "source_user_id"),
                name="uniq_import_job_source_user",
            ),
            # Two source identities cannot collapse onto one target account: they could
            # not both create a MakerspaceMembership (unique by makerspace + user), and
            # doing so would silently merge immutable attribution, registrations, and
            # payments onto one person.
            models.UniqueConstraint(
                fields=("job", "target_user"),
                condition=Q(target_user__isnull=False),
                name="uniq_import_job_target_user",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.identity_resolution == self.IdentityResolution.CREATE_WALK_IN
            and self.target_user_id is not None
        ):
            raise ValidationError(
                {"target_user": "A walk-in decision cannot name an existing account."}
            )
