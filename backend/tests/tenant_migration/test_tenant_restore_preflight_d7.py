from dataclasses import replace

import pytest

from apps.tenant_migration.tenant_restore_preflight import validate_static_preflight
from apps.tenant_migration.tenant_restore_types import (
    ArtifactPreflight,
    PrivilegeFacts,
    ResourceIdentity,
    SiblingPlan,
    StaticPreflight,
    TenantRestoreRefused,
    TopologyPreflight,
)


def valid_facts():
    current = ResourceIdentity("target:5432", "active", "a", 1)
    return StaticPreflight(
        artifact=ArtifactPreflight(*([True] * 12)),
        topology=TopologyPreflight(
            True, True, current, "image", True, True, ("backend", "worker")
        ),
        privileges=PrivilegeFacts(True, True, True, True, True, True),
        sibling=SiblingPlan(False, True, True, "candidate"),
        source_identity=ResourceIdentity("source:5432", "source", "s", 2),
        scratch_identity=ResourceIdentity("scratch:5432", "scratch", "x", 3),
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda f: replace(f, privileges=replace(f.privileges, probed=False)), "cannot be probed"),
        (
            lambda f: replace(
                f, privileges=replace(f.privileges, can_create_database=False)
            ),
            "creation is unavailable",
        ),
        (
            lambda f: replace(
                f, sibling=replace(f.sibling, non_routable_guaranteed=False)
            ),
            "non-routable",
        ),
        (
            lambda f: replace(
                f,
                sibling=replace(
                    f.sibling, supplied=True, provider_guarantees_empty=False
                ),
            ),
            "empty sibling",
        ),
        (
            lambda f: replace(
                f, privileges=replace(f.privileges, can_exclude_sessions=False)
            ),
            "sessions cannot be excluded",
        ),
        (
            lambda f: replace(
                f, topology=replace(f.topology, pointer_compare_and_swap=False)
            ),
            "lacks compare-and-swap",
        ),
        (
            lambda f: replace(
                f, sibling=replace(f.sibling, planned_identity=f.source_identity)
            ),
            "identities match",
        ),
        (
            lambda f: replace(f, scratch_identity=f.source_identity),
            "identities match",
        ),
        (
            lambda f: replace(
                f, topology=replace(f.topology, exact_current_identity=f.source_identity)
            ),
            "identities match",
        ),
    ],
)
def test_each_52_refusal_happens_in_static_preflight(mutate, message):
    facts = mutate(valid_facts())

    with pytest.raises(TenantRestoreRefused, match=message):
        validate_static_preflight(facts)


@pytest.mark.parametrize("field", ArtifactPreflight.__dataclass_fields__)
def test_each_static_artifact_fact_refuses_before_allocation(field):
    facts = valid_facts()
    artifact = replace(facts.artifact, **{field: False})

    with pytest.raises(TenantRestoreRefused):
        validate_static_preflight(replace(facts, artifact=artifact))


@pytest.mark.parametrize(
    "field",
    ("can_restore_schema", "can_apply_ownership", "can_apply_runtime_grants"),
)
def test_each_restore_ownership_privilege_is_required(field):
    facts = valid_facts()
    privileges = replace(facts.privileges, **{field: False})

    with pytest.raises(TenantRestoreRefused, match="ownership or restore grants"):
        validate_static_preflight(replace(facts, privileges=privileges))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adapter_supported", False),
        ("exact_current_identity", None),
        ("cloud_config_digest_matches", False),
        ("static_config_initialized", False),
        ("scheduler_mode", "undeclared"),
        ("complete_writer_set", ()),
    ],
)
def test_each_topology_fact_refuses_before_allocation(field, value):
    facts = valid_facts()

    with pytest.raises(TenantRestoreRefused):
        validate_static_preflight(
            replace(facts, topology=replace(facts.topology, **{field: value}))
        )


def test_supplied_sibling_does_not_require_createdb_but_still_requires_empty_proof():
    facts = valid_facts()
    facts = replace(
        facts,
        privileges=replace(facts.privileges, can_create_database=False),
        sibling=replace(facts.sibling, supplied=True),
    )
    assert validate_static_preflight(facts) is facts


def test_valid_static_preflight_is_read_only_and_accepted():
    facts = valid_facts()
    assert validate_static_preflight(facts) is facts
