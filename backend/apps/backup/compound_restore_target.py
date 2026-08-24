"""Concrete target-state adapter backed by the E7 database services."""

from django.db import connections

from apps.backup.database_identity import query_live_database_identity
from apps.backup.models import DeploymentRecoveryState
from apps.tenant_migration.tenant_restore_target_state import (
    establish_target_import_state,
    set_target_normal,
)

from .compound_restore_state import (
    install_manifest_enforcement,
    mark_quarantine_verified,
    readiness_declarations,
    rehydrate_pre_cutover_state,
    verify_pre_cutover_state,
)


class DatabaseStateTarget:
    def __init__(self, *, using, acknowledgement):
        self.using = using
        self.acknowledgement = acknowledgement

    def rehydrate(self, sibling, inputs, manifest):
        identity = establish_target_import_state(
            run_id=inputs.run_id,
            artifact_sha256=inputs.artifact_sha256,
            capture_id=inputs.capture_id,
            using=self.using,
        )
        state = rehydrate_pre_cutover_state(
            inputs=inputs,
            manifest=manifest,
            sibling=sibling,
            using=self.using,
        )
        return {
            **state,
            "database_uuid": str(identity.database_uuid),
            "recovery_mode": DeploymentRecoveryState.Mode.TARGET_IMPORT,
        }

    def install_enforcement(self, _sibling, inputs, manifest):
        return install_manifest_enforcement(
            inputs=inputs, manifest=manifest, using=self.using
        )

    def verify_catalog(self, _sibling, inputs, _manifest):
        return verify_pre_cutover_state(inputs=inputs, using=self.using)

    def prepare_quarantine(self, _sibling, _inputs, _manifest):
        return {"marker_readiness": readiness_declarations(using=self.using)}

    def verify_quarantine(self, sibling, inputs, _manifest):
        proof = self.acknowledgement.verify_candidate_readiness(
            sibling=sibling, inputs=inputs
        )
        if not isinstance(proof, dict) or proof.get("verified") is not True:
            return {"verified": False}
        return {
            **mark_quarantine_verified(inputs=inputs, using=self.using),
            "probe": proof,
        }

    def acknowledge_recovery(self, sibling, inputs):
        result = self.acknowledgement.acknowledge(sibling=sibling, inputs=inputs)
        if not isinstance(result, dict) or result.get("acknowledged") is not True:
            return {"acknowledged": False}
        live = query_live_database_identity(connections[self.using])
        expected = {
            "database_uuid": live.database_uuid,
            "run_id": inputs.run_id,
            "artifact_sha256": inputs.artifact_sha256,
            "capture_id": inputs.capture_id,
        }
        state = DeploymentRecoveryState.objects.using(self.using).get(pk=1)
        if state.mode == DeploymentRecoveryState.Mode.TARGET_IMPORT:
            set_target_normal(expected_identity=expected, using=self.using)
        elif state.mode != DeploymentRecoveryState.Mode.NORMAL:
            return {"acknowledged": False}
        return {**result, "recovery_mode": DeploymentRecoveryState.Mode.NORMAL}
