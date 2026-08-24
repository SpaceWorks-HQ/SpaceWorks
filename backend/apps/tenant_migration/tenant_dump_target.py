"""D5 facade binding pre-destructive identity proof to target reconstruction."""

from dataclasses import dataclass

from .tenant_dump_errors import TenantDumpTargetError
from .tenant_dump_lineage import FORMAT, canonical_digest
from .tenant_dump_target_custody import (
    assert_imported_part_a_operational_rows_absent,
    prove_imported_tenant_recipients,
    target_custody_readiness,
)
from .tenant_dump_target_deks import install_target_deks
from .tenant_dump_target_identities import preflight_target_identities
from .tenant_dump_target_readiness import (
    rebuild_and_verify_target_encryption,
    run_target_encryption_readiness,
)


@dataclass(frozen=True, repr=False)
class TargetIdentityPreflight:
    source_makerspace_id: int
    source_pii_mode: str
    manifest_digest: str
    identities: tuple


def preflight_target_identity_input(
    manifest,
    identity_paths,
    *,
    environ=None,
    command_argv=None,
    mountinfo_path="/proc/self/mountinfo",
):
    """Run the identity checks that must precede sibling allocation or restore."""
    source = manifest.get("source") if isinstance(manifest, dict) else None
    if manifest.get("format") != FORMAT or not isinstance(source, dict):
        _refuse("The Lane D target manifest is invalid.", "manifest_invalid")
    makerspace_id = source.get("makerspace_id")
    mode = manifest.get("source_pii_mode")
    recipients = source.get("tenant_recipients")
    if type(makerspace_id) is not int or makerspace_id <= 0:
        _refuse("The source makerspace identity is invalid.", "manifest_invalid")
    if mode not in {"plaintext", "encrypted"} or not isinstance(recipients, list):
        _refuse("The Lane D target encryption declaration is invalid.", "manifest_invalid")
    identities = preflight_target_identities(
        identity_paths,
        recipients,
        environ=environ,
        command_argv=command_argv,
        mountinfo_path=mountinfo_path,
    )
    return TargetIdentityPreflight(
        source_makerspace_id=makerspace_id,
        source_pii_mode=mode,
        manifest_digest=canonical_digest(manifest),
        identities=identities,
    )


def install_and_verify_target_encryption(
    manifest,
    envelope_path,
    preflight,
    *,
    safety,
    actor=None,
    batch_size=500,
):
    """Run D5 steps 1-7 for an encrypted target after pg_restore."""
    _require_bound_preflight(manifest, preflight)
    versions = install_target_deks(
        manifest,
        envelope_path,
        preflight.identities,
        safety=safety,
    )
    readiness = rebuild_and_verify_target_encryption(
        preflight.source_makerspace_id,
        actor=actor,
        batch_size=batch_size,
    )
    return versions, readiness


def reconstruct_target_recipient_custody(preflight, *, actor=None):
    """Re-prove matching carried recipients and derive both target custody states."""
    assert_imported_part_a_operational_rows_absent(
        preflight.source_makerspace_id
    )
    proven = prove_imported_tenant_recipients(
        preflight.source_makerspace_id,
        preflight.identities,
        actor=actor,
    )
    return proven, target_custody_readiness(preflight.source_makerspace_id)


def assert_target_d5_activation_ready(makerspace_id):
    """Re-run D5 readiness immediately before a future activation transition."""
    encryption = run_target_encryption_readiness(makerspace_id)
    custody = target_custody_readiness(makerspace_id)
    return encryption, custody


def _require_bound_preflight(manifest, preflight):
    if (
        type(preflight) is not TargetIdentityPreflight
        or preflight.manifest_digest != canonical_digest(manifest)
        or preflight.source_pii_mode != "encrypted"
    ):
        _refuse(
            "Target reconstruction requires the matching pre-destructive identity preflight.",
            "identity_preflight_mismatch",
        )


def _refuse(message, code):
    raise TenantDumpTargetError(message, code=code)
