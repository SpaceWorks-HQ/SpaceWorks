"""D7 refusal rules evaluated before any target state is created."""

from .tenant_restore_types import ResourceIdentity, StaticPreflight, TenantRestoreRefused


def validate_static_preflight(
    facts: StaticPreflight, *, allow_committed_sibling=False
) -> StaticPreflight:
    artifact = facts.artifact
    checks = (
        (artifact.artifact_sha256_ok, "Artifact digest verification failed."),
        (artifact.outer_sha256_ok, "Outer digest verification failed."),
        (artifact.inner_sha256_ok, "Inner digest verification failed."),
        (artifact.format_ok, "Artifact format is not Lane D."),
        (artifact.build_compatible, "Target build is incompatible."),
        (artifact.schema_compatible, "Target schema is incompatible."),
        (artifact.postgres_compatible, "PostgreSQL major compatibility is unprovable."),
        (artifact.encryption_mode_matches, "Target encryption mode differs from source."),
        (artifact.tenant_fingerprint_matches, "Tenant identity fingerprint differs."),
        (artifact.target_crypto_keys_ready, "Target broker or search key is unavailable."),
        (artifact.object_capacity_sufficient, "Target object capacity is insufficient."),
        (artifact.api_approval_valid, "API-client approval file is invalid."),
    )
    for accepted, reason in checks:
        if accepted is not True:
            raise TenantRestoreRefused(reason)

    topology = facts.topology
    if topology.adapter_supported is not True:
        raise TenantRestoreRefused("The declared topology adapter is unsupported.")
    if topology.pointer_compare_and_swap is not True:
        raise TenantRestoreRefused("The pointer store lacks compare-and-swap.")
    if not isinstance(topology.exact_current_identity, ResourceIdentity):
        raise TenantRestoreRefused("The exact current database identity is unavailable.")
    if (
        topology.static_config_initialized is not True
        or topology.cloud_config_digest_matches is not True
    ):
        raise TenantRestoreRefused("Cloud static configuration is missing or drifted.")
    if topology.scheduler_mode not in {"image", "external"}:
        raise TenantRestoreRefused("The scheduler mode is undeclared.")
    if (
        not isinstance(topology.complete_writer_set, tuple)
        or not topology.complete_writer_set
        or any(not isinstance(writer, str) or not writer for writer in topology.complete_writer_set)
        or len(set(topology.complete_writer_set)) != len(topology.complete_writer_set)
    ):
        raise TenantRestoreRefused("The topology has no complete writer declaration.")

    privileges = facts.privileges
    if privileges.probed is not True:
        raise TenantRestoreRefused("Target privileges cannot be probed.")
    if facts.sibling.supplied is not True and privileges.can_create_database is not True:
        raise TenantRestoreRefused(
            "Database creation is unavailable and no sibling was supplied."
        )
    if any(value is not True for value in (
        privileges.can_restore_schema, privileges.can_apply_ownership,
        privileges.can_apply_runtime_grants,
    )):
        raise TenantRestoreRefused("Target ownership or restore grants are insufficient.")
    if privileges.can_exclude_sessions is not True:
        raise TenantRestoreRefused("Target sessions cannot be excluded.")

    sibling = facts.sibling
    if type(sibling.supplied) is not bool:
        raise TenantRestoreRefused("The sibling ownership plan is invalid.")
    if sibling.non_routable_guaranteed is not True:
        raise TenantRestoreRefused("The provider cannot guarantee a non-routable sibling.")
    if sibling.provider_guarantees_empty is not True:
        raise TenantRestoreRefused("The provider cannot guarantee an empty sibling.")
    if not isinstance(sibling.planned_name, str) or not sibling.planned_name:
        raise TenantRestoreRefused("The sibling plan has no exact resource name.")
    if not isinstance(facts.source_identity, ResourceIdentity) or (
        facts.scratch_identity is not None
        and not isinstance(facts.scratch_identity, ResourceIdentity)
    ):
        raise TenantRestoreRefused("Source or scratch identity is unprovable.")
    if sibling.planned_identity is not None and not isinstance(
        sibling.planned_identity, ResourceIdentity
    ):
        raise TenantRestoreRefused("The sibling identity is unprovable.")
    identities = [facts.source_identity, topology.exact_current_identity]
    if facts.scratch_identity is not None:
        identities.append(facts.scratch_identity)
    durable = [identity.durable_key() for identity in identities]
    if len(set(durable)) != len(durable):
        raise TenantRestoreRefused("Source and scratch/sibling identities match.")
    if sibling.planned_identity is not None:
        compared = [facts.source_identity]
        if facts.scratch_identity is not None:
            compared.append(facts.scratch_identity)
        if not allow_committed_sibling:
            compared.append(topology.exact_current_identity)
        if sibling.planned_identity.durable_key() in {
            identity.durable_key() for identity in compared
        }:
            raise TenantRestoreRefused("Source and scratch/sibling identities match.")
    return facts
