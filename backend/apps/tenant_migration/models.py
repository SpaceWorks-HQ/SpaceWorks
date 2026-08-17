from django.db import models

from .schemas import validate_snapshot

# Re-exported so Django registers the split models and callers retain the stable
# `apps.tenant_migration.models` import path.
from .models_import_job import ImportIdentityDecision, TenantImportJob  # noqa: F401,E402
from .models_protocol import (  # noqa: F401,E402
    DisclosureClosureApproval,
    DeploymentSigningKey,
    MigratedOutHandoff,
    MigrationPairing,
    MigrationReceipt,
    ReceiptConsumption,
    TenantMigrationExportJob,
)
from .models_source_gate import SourceMigrationGate  # noqa: F401,E402


class ExternalTenantReference(models.Model):
    """Typed provenance for a source reference that cannot become a live target FK."""

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="external_tenant_references",
    )
    source_archive_digest = models.CharField(max_length=64)
    # These labels differ intentionally: a collaborator source row is an
    # EventCollaborator, while the imported row anchoring its provenance is an Event.
    source_model_label = models.CharField(max_length=100)
    source_object_id = models.CharField(max_length=64)
    field_name = models.CharField(max_length=64)
    target_model_label = models.CharField(max_length=100, blank=True)
    target_object_id = models.CharField(max_length=64, blank=True)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "makerspace",
                    "source_archive_digest",
                    "source_model_label",
                    "source_object_id",
                    "field_name",
                ),
                name="uniq_external_tenant_reference",
            ),
        ]
        indexes = [
            # Deliberately non-unique: several foreign EventCollaborator rows can all
            # anchor to the same imported hosted Event.
            models.Index(
                fields=("makerspace", "target_model_label", "target_object_id")
            ),
        ]

    def clean(self):
        super().clean()
        validate_snapshot(self.source_model_label, self.field_name, self.snapshot)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
