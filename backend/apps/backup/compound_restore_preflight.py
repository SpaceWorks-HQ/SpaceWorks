"""Read-only compound admission before the host ledger records any effect."""

from apps.backup.import_preflight import (
    ImportPreflightError,
    validate_import_preflight,
)

from .compound_restore_types import CompoundRestoreRefused, CompoundTopologyFacts


def validate_compound_preflight(
    inputs, *, pointer, database, capability, allow_committed_cutover=False
):
    """Reuse E9a and then prove every host-only topology capability."""

    try:
        result = validate_import_preflight(
            encrypted_file=inputs.encrypted_file,
            bundle=inputs.bundle,
            manifest_file=inputs.manifest_file,
            continuity_secrets_file=inputs.continuity_secrets_file,
            expected_sha256=inputs.expected_sha256,
        )
    except ImportPreflightError as exc:
        raise CompoundRestoreRefused(str(exc)) from exc
    if result.archive_sha256 != inputs.artifact_sha256:
        raise CompoundRestoreRefused("The coordinator artifact digest changed after admission.")
    if str(result.manifest.get("capture_id")) != str(inputs.capture_id):
        raise CompoundRestoreRefused("The coordinator capture identity does not match the artifact.")

    topology = pointer.preflight(
        allow_committed_cutover=allow_committed_cutover
    )
    _validate_topology(topology)
    generation = pointer.current_generation()
    if type(generation) is not int or generation < 1:
        raise CompoundRestoreRefused(
            f"The {topology.path} restore path has no positive durable generation."
        )
    database_facts = database.preflight()
    required = {
        "privileges_probed", "can_restore", "can_apply_grants",
        "can_exclude_sessions", "empty_sibling", "non_routable_sibling",
    }
    if not isinstance(database_facts, dict) or set(database_facts) != required:
        raise CompoundRestoreRefused("The target database capability probe is incomplete.")
    if any(database_facts[name] is not True for name in required):
        failed = next(name for name in sorted(required) if database_facts[name] is not True)
        raise CompoundRestoreRefused(
            f"The target database capability probe refused {failed.replace('_', ' ')}."
        )
    capability_facts = capability.validate(
        inputs=inputs, manifest=result.manifest, topology=topology
    )
    if not isinstance(capability_facts, dict) or capability_facts.get("validated") is not True:
        raise CompoundRestoreRefused("The installed compound host capability is invalid.")
    return result, topology, capability_facts


def _validate_topology(facts):
    if not isinstance(facts, CompoundTopologyFacts):
        raise CompoundRestoreRefused("The selected restore path has no topology adapter.")
    checks = (
        (facts.atomic_pointer_swap, "atomic rename or store-native CAS"),
        (facts.durable_generation, "a durable pointer generation"),
        (facts.identity_query, "an authoritative live database identity query"),
        (facts.complete_writer_rollout, "a complete writer rollout"),
        (facts.safe_sibling_lifecycle, "a safe sibling lifecycle"),
    )
    for accepted, description in checks:
        if accepted is not True:
            raise CompoundRestoreRefused(
                f"The {facts.path} restore path cannot provide {description}."
            )
    if not facts.writer_set or len(set(facts.writer_set)) != len(facts.writer_set):
        raise CompoundRestoreRefused(
            f"The {facts.path} restore path has no exact complete writer set."
        )
    if (
        facts.authoritative_database_url == "external"
        and facts.external_journalled_swap is not True
    ):
        raise CompoundRestoreRefused(
            "The external authoritative DATABASE_URL control plane has no journalled swap."
        )
