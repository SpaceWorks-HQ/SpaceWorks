"""Durable, database-enforced Lane E restore reservation state."""

from django.db import models


class B1RestoreOperationState(models.Model):
    """Ordered pre-cutover facts for one compound restore attempt.

    Identity and proof bindings never change.  ``stage`` may only advance through
    the database transition trigger installed by the E7 restore coordinator.
    """

    class Stage(models.TextChoices):
        VERIFIED = "verified", "Outer artifact verified"
        MAIN_RESTORED = "main_restored", "Readable main restored"
        ROLES_RECREATED = "roles_recreated", "Roles and grants recreated"
        STATE_REHYDRATED = "state_rehydrated", "Private state rehydrated"
        ENFORCEMENT_INSTALLED = "enforcement_installed", "Enforcement installed"
        CATALOG_VERIFIED = "catalog_verified", "Catalog and reservations verified"
        OBJECTS_VERIFIED = "objects_verified", "Main objects verified"
        QUARANTINE_VERIFIED = "quarantine_verified", "Sibling quarantine verified"
        CUTOVER_READY = "cutover_ready", "Authenticated cutover handoff ready"
        FAILED = "failed", "Failed closed"

    operation_id = models.UUIDField(primary_key=True, editable=False)
    artifact_id = models.UUIDField(editable=False)
    capture_id = models.UUIDField(editable=False)
    main_component_id = models.UUIDField(editable=False)
    outer_ciphertext_sha256 = models.CharField(max_length=64, editable=False)
    outer_manifest_sha256 = models.CharField(max_length=64, editable=False)
    source_proof_sha256 = models.CharField(max_length=64, editable=False)
    sibling_database_name = models.CharField(max_length=63, editable=False)
    sibling_database_oid = models.PositiveBigIntegerField(editable=False)
    sibling_server_identity = models.CharField(max_length=255, editable=False)
    stage = models.CharField(
        max_length=32, choices=Stage.choices, default=Stage.VERIFIED
    )
    fence_continuity_digest = models.CharField(max_length=64, blank=True)
    object_journal_evidence_sha256 = models.CharField(max_length=64, blank=True)
    quarantine_evidence_sha256 = models.CharField(max_length=64, blank=True)
    cutover_attestation = models.JSONField(default=dict, blank=True)
    failure_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Compound restore operation state cannot be deleted.")


class B1RestoreComponentState(models.Model):
    """One current opaque-slice state, addressable without a Makerspace row."""

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        DEPENDENCY_WAIT = "dependency_wait", "Waiting for a dependency"
        MERGING = "merging", "Merging"
        RESTORED = "restored", "Restored"
        FAILED = "failed", "Failed"

    class MergeCheckpoint(models.TextChoices):
        STAGED = "staged", "Raw slice staged"
        KEYS_INSTALLED = "keys_installed", "Target keys installed"
        ROWS_APPLIED = "rows_applied", "Rows applied"
        OBJECTS_PROMOTED = "objects_promoted", "Objects promoted"
        VERIFIED = "verified", "Final verification complete"

    operation_id = models.UUIDField(editable=False)
    artifact_id = models.UUIDField(editable=False)
    capture_id = models.UUIDField(editable=False)
    component_id = models.UUIDField(editable=False)
    makerspace_id_snapshot = models.PositiveBigIntegerField(editable=False)
    ciphertext_sha256 = models.CharField(max_length=64, editable=False)
    state = models.CharField(max_length=24, choices=State.choices)
    dependency_facts = models.JSONField(default=list, blank=True, editable=False)
    merge_checkpoint = models.CharField(
        max_length=24, choices=MergeCheckpoint.choices, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("operation_id", "component_id"),
                name="uniq_b1_restore_operation_component",
            ),
            models.UniqueConstraint(
                fields=("artifact_id", "component_id"),
                name="uniq_b1_restore_artifact_component",
            ),
            models.UniqueConstraint(
                fields=("makerspace_id_snapshot",),
                condition=~models.Q(state="restored"),
                name="uniq_b1_active_component_per_space",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("Restore component history cannot be deleted.")


class B1ReservationEntry(models.Model):
    """Manifest-safe reservation or fence facts installed for one component."""

    class Kind(models.TextChoices):
        COMMITMENT = "commitment", "High-entropy commitment"
        NUMERIC_RANGE = "numeric_range", "Numeric range"
        BROAD_FENCE = "broad_fence", "Broad data fence"
        RELATIONSHIP_FENCE = "relationship_fence", "Relationship fence"
        OBJECT_NAMESPACE = "object_namespace", "Object namespace fence"

    operation_id = models.UUIDField(editable=False)
    component_id = models.UUIDField(editable=False)
    registry_identity = models.CharField(max_length=64, editable=False)
    kind = models.CharField(max_length=32, choices=Kind.choices, editable=False)
    definition_sha256 = models.CharField(max_length=64, editable=False)
    safe_payload = models.JSONField(default=dict, editable=False)
    installed_at = models.DateTimeField(null=True, blank=True)
    catalog_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("operation_id", "component_id", "registry_identity", "kind"),
                name="uniq_b1_component_reservation",
            )
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("Restore reservations cannot be deleted.")


class B1FenceContinuity(models.Model):
    """Append-only proof that a required database fence was never absent."""

    operation_id = models.UUIDField(editable=False)
    registry_identity = models.CharField(max_length=64, editable=False)
    definition_sha256 = models.CharField(max_length=64, editable=False)
    trigger_oids = models.JSONField(default=list, editable=False)
    installed_at = models.DateTimeField(auto_now_add=True)
    last_verified_at = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=True, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("operation_id", "registry_identity"),
                name="uniq_b1_fence_continuity",
            ),
            models.CheckConstraint(
                condition=models.Q(enabled=True),
                name="b1_fence_continuity_enabled",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("Fence continuity records cannot be deleted.")
