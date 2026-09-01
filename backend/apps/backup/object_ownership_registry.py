"""Typed object-reference surfaces for Lane E compound archives."""

from dataclasses import dataclass
from enum import StrEnum

from django.apps import apps

from apps.backup.archive_objects import OBJECT_FIELD_NAMES
from apps.backup.recipient_selection import BackupBuildError


class BucketRule(StrEnum):
    PRIVATE = "private"
    PUBLIC_IMAGE = "public_image"
    FROM_ROW = "from_row"


class ReferencePolicy(StrEnum):
    CANONICAL = "canonical"
    COORDINATION_ONLY = "coordination_only"
    PACKAGE_MAIN_COORDINATION = "package_main_coordination"


@dataclass(frozen=True)
class FieldObjectRule:
    model_label: str
    field_name: str
    bucket: BucketRule
    policy: ReferencePolicy = ReferencePolicy.CANONICAL
    coordination_path: str | None = None
    coordination_reason: str = ""


# Literal, field-specific declarations are intentional. The equality guard below
# makes adding an object-bearing concrete field a preflight failure.
FIELD_OBJECT_RULES = (
    FieldObjectRule("backup.BackupArchive", "object_key", BucketRule.PRIVATE,
                    ReferencePolicy.COORDINATION_ONLY,
                    coordination_path="makerspace_id",
                    coordination_reason="recursive_archive_reference"),
    FieldObjectRule("backup.RestoreRollbackObject", "copy_key", BucketRule.FROM_ROW,
                    coordination_path="makerspace_id",
                    coordination_reason="restore_rollback_coordination"),
    FieldObjectRule("tenant_migration.TenantDumpCapture", "object_key",
                    BucketRule.PRIVATE, ReferencePolicy.COORDINATION_ONLY,
                    coordination_path="makerspace_id",
                    coordination_reason="recursive_tenant_exit_artifact"),
    FieldObjectRule("bookings.BookableSpace", "image_key", BucketRule.PUBLIC_IMAGE),
    FieldObjectRule("data_export.DataExportJob", "object_key", BucketRule.PRIVATE,
                    coordination_path="makerspace_id",
                    coordination_reason="data_export_coordination"),
    FieldObjectRule("events.Event", "image_key", BucketRule.PUBLIC_IMAGE),
    FieldObjectRule("evidence.EvidencePhoto", "object_key", BucketRule.PRIVATE),
    FieldObjectRule("inventory.InventoryProduct", "image_key", BucketRule.PUBLIC_IMAGE),
    FieldObjectRule("machines.Machine", "image_key", BucketRule.PUBLIC_IMAGE),
    FieldObjectRule("machines.MachineDocument", "object_key", BucketRule.PRIVATE),
    FieldObjectRule("machines.ServiceRequestFile", "object_key", BucketRule.PRIVATE),
    FieldObjectRule("maintenance.MaintenanceLogDocument", "object_key", BucketRule.PRIVATE),
    FieldObjectRule("makerspaces.Makerspace", "cover_image_key", BucketRule.PUBLIC_IMAGE),
    FieldObjectRule("makerspaces.Makerspace", "logo_key", BucketRule.PUBLIC_IMAGE),
    FieldObjectRule("makerspaces.MemberProfile", "avatar_key", BucketRule.PUBLIC_IMAGE),
    FieldObjectRule("makerspaces.MemberProject", "image_key", BucketRule.PUBLIC_IMAGE),
    FieldObjectRule("organizations.Organization", "logo_key", BucketRule.PUBLIC_IMAGE),
    FieldObjectRule("procurement.ToBuyReceipt", "object_key", BucketRule.PRIVATE),
    FieldObjectRule("warranty.WarrantyDocument", "object_key", BucketRule.PRIVATE),
)

AUDIT_META_OBJECT_VARIANTS = {
    "machine.document_added": "object_key",
    "machine.document_removed": "object_key",
}


def validate_object_reference_registry():
    actual = {
        (model._meta.label, field.name)
        for model in apps.get_models()
        for field in model._meta.concrete_fields
        if field.name in OBJECT_FIELD_NAMES
    }
    declared = {(rule.model_label, rule.field_name) for rule in FIELD_OBJECT_RULES}
    if actual != declared:
        raise BackupBuildError(
            "Lane E object-reference field registry drift: "
            f"unclassified={sorted(actual - declared)}, absent={sorted(declared - actual)}."
        )
    return FIELD_OBJECT_RULES
