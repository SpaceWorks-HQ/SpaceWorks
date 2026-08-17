import uuid

from django.conf import settings
from django.db import models


class DeploymentSigningKey(models.Model):
    """The singleton deployment identity; the private half is Fernet-encrypted."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    deployment_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    private_key_ciphertext = models.TextField(editable=False)
    public_key = models.CharField(max_length=44, editable=False)
    fingerprint = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)


class DisclosureClosureApproval(models.Model):
    """A source-superadmin decision bound to one exact PORTABLE identity closure."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="migration_disclosure_approvals",
    )
    closure_digest = models.CharField(max_length=64)
    identity_ids = models.JSONField(default=list)
    approved_identity_ids = models.JSONField(default=list)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_migration_disclosures",
    )
    approved_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_migration_disclosures",
    )

    class Meta:
        indexes = [
            models.Index(
                fields=("makerspace", "closure_digest", "revoked_at"),
                name="tdisclosure_space_digest_idx",
            )
        ]


class TenantMigrationExportJob(models.Model):
    """Migration-only state attached to the existing export/token lifecycle."""

    export_job = models.OneToOneField(
        "data_export.DataExportJob",
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="migration_export",
    )
    disclosure_approval = models.ForeignKey(
        DisclosureClosureApproval,
        on_delete=models.PROTECT,
        related_name="export_jobs",
    )
    closure_digest = models.CharField(max_length=64)
    target_age_recipient = models.CharField(max_length=256)
    format_version = models.PositiveSmallIntegerField(default=1)
    archive_digest = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class MigrationPairing(models.Model):
    """Superadmin-approved, locally pinned identities for one migration."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    migration_id = models.UUIDField(unique=True)
    source_tenant_id = models.CharField(max_length=64)
    archive_digest = models.CharField(max_length=64)
    source_deployment_id = models.CharField(max_length=128)
    source_public_key = models.CharField(max_length=44)
    source_fingerprint = models.CharField(max_length=64)
    target_deployment_id = models.CharField(max_length=128)
    target_public_key = models.CharField(max_length=44)
    target_fingerprint = models.CharField(max_length=64)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_tenant_migration_pairings",
    )
    approved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(source_deployment_id=models.F("target_deployment_id")),
                name="ck_tpair_distinct_deployments",
            ),
            models.CheckConstraint(
                condition=~models.Q(source_fingerprint=models.F("target_fingerprint")),
                name="ck_tpair_distinct_fingerprints",
            ),
        ]


class MigrationReceipt(models.Model):
    class Operation(models.TextChoices):
        SOURCE_CUTOVER = "source_cutover", "Source cutover"
        TARGET_ABORT = "target_abort", "Target abort"

    receipt_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pairing = models.ForeignKey(
        MigrationPairing,
        on_delete=models.PROTECT,
        related_name="receipts",
    )
    format_version = models.PositiveSmallIntegerField(default=1)
    operation = models.CharField(max_length=24, choices=Operation.choices)
    migration_id = models.UUIDField()
    source_tenant_id = models.CharField(max_length=64)
    archive_digest = models.CharField(max_length=64)
    source_deployment_id = models.CharField(max_length=128)
    target_deployment_id = models.CharField(max_length=128)
    signer_fingerprint = models.CharField(max_length=64)
    signature = models.CharField(max_length=88)
    issued_here = models.BooleanField(default=False)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("pairing", "operation"),
                name="uniq_treceipt_pairing_operation",
            ),
        ]


class ReceiptConsumption(models.Model):
    class Purpose(models.TextChoices):
        ACTIVATE_TARGET = "activate_target", "Activate target"
        REOPEN_SOURCE = "reopen_source", "Reopen source"

    receipt = models.OneToOneField(
        MigrationReceipt,
        primary_key=True,
        on_delete=models.PROTECT,
        related_name="consumption",
    )
    purpose = models.CharField(max_length=24, choices=Purpose.choices)
    consumed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="consumed_tenant_migration_receipts",
    )
    consumed_at = models.DateTimeField(auto_now_add=True)


class MigratedOutHandoff(models.Model):
    class State(models.TextChoices):
        MIGRATED_OUT = "migrated_out", "Migrated out"

    source_tenant = models.OneToOneField(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="migration_handoff",
    )
    pairing = models.OneToOneField(
        MigrationPairing,
        on_delete=models.PROTECT,
        related_name="source_handoff",
    )
    archive_digest = models.CharField(max_length=64)
    target_deployment_id = models.CharField(max_length=128)
    state = models.CharField(
        max_length=24,
        choices=State.choices,
        default=State.MIGRATED_OUT,
        editable=False,
    )
    source_cutover_receipt = models.OneToOneField(
        MigrationReceipt,
        on_delete=models.PROTECT,
        related_name="source_handoff",
    )
    migrated_out_at = models.DateTimeField(auto_now_add=True)
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reopened_tenant_migration_handoffs",
    )
    abort_receipt = models.OneToOneField(
        MigrationReceipt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reopened_handoff",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("source_tenant", "archive_digest", "target_deployment_id"),
                name="uniq_migrated_out_handoff_binding",
            ),
        ]
