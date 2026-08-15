from dataclasses import replace

import pytest

from apps.data_export.datasets import DATASETS
from apps.data_export.fields import FIELDS, USER_PROJECTIONS
from apps.data_export.guards import (
    RegistryError,
    resolve_source_path,
    validate_all,
    validate_dataset_contract,
    validate_model_and_field_coverage,
    validate_semantic_references,
    validate_user_edges,
)
from apps.data_export.references import SEMANTIC_REFERENCES, USER_EDGES
from apps.data_export.traversals import TRAVERSALS
from apps.data_export.types import Column, Fidelity, Transformed


def _dataset(fidelity, path):
    return DATASETS[(fidelity, path)]


def _replace_dataset(registry, dataset):
    changed = dict(registry)
    changed[(dataset.fidelity, dataset.path)] = dataset
    return changed


def test_complete_registry_is_valid():
    validate_all()


def test_field_disposition_guard_detects_missing_field():
    fields = dict(FIELDS)
    fields.pop((Fidelity.REDACTED, "inventory.Category", "name"))

    with pytest.raises(RegistryError, match="field dispositions"):
        validate_model_and_field_coverage(fields)


def test_source_path_must_resolve_against_real_model_graph():
    source = _dataset(Fidelity.REDACTED, "inventory/categories.csv")
    bad_column = replace(source.columns[0], sources=("not_a_real_field",))
    changed = replace(source, columns=(bad_column,) + source.columns[1:])

    with pytest.raises(RegistryError, match="does not resolve"):
        validate_dataset_contract(_replace_dataset(DATASETS, changed))


@pytest.mark.parametrize(
    ("fidelity", "path", "source", "message"),
    [
        (
            Fidelity.PORTABLE,
            "makerspace/config.csv",
            "smtp_password",
            "launders omitted",
        ),
        (
            Fidelity.REDACTED,
            "audit/audit_log.csv",
            "meta",
            "launders redacted",
        ),
    ],
)
def test_derived_column_cannot_launder_forbidden_source(fidelity, path, source, message):
    dataset = _dataset(fidelity, path)
    leak = Column("innocent_name", (source,), Transformed("bad derived value"))
    retained = tuple(
        column for column in dataset.columns if source not in column.sources
    )
    changed = replace(dataset, columns=retained + (leak,))

    with pytest.raises(RegistryError, match=message):
        validate_dataset_contract(_replace_dataset(DATASETS, changed))


def test_many_to_many_source_is_rejected_structurally():
    dataset = _dataset(Fidelity.PORTABLE, "global/users.csv")
    leak = Column("group_ids", ("groups",), Transformed("privilege expansion"))
    changed = replace(dataset, columns=dataset.columns + (leak,))

    with pytest.raises(RegistryError, match="M2M traversal is forbidden"):
        validate_dataset_contract(_replace_dataset(DATASETS, changed))


def test_every_relationship_hop_requires_permission():
    traversals = {key: frozenset() for key in Fidelity}

    with pytest.raises(RegistryError, match="relationship hop is not permitted"):
        validate_dataset_contract(DATASETS, traversals=traversals)


def test_external_routing_hop_remains_forbidden_even_if_added_to_allowlist():
    traversals = dict(TRAVERSALS)
    traversals[Fidelity.PORTABLE] |= {
        ("payments.Payment", "via_makerspace")
    }

    with pytest.raises(RegistryError, match="relationship hop is not permitted"):
        resolve_source_path(
            Fidelity.PORTABLE,
            "payments.Payment",
            "via_makerspace__branding_config",
            traversals,
        )


def test_dataset_paths_are_unique():
    rows = list(DATASETS.values())
    rows.append(rows[0])

    with pytest.raises(RegistryError, match="duplicate dataset paths"):
        validate_dataset_contract(rows)


def test_dataset_column_names_are_unique():
    dataset = _dataset(Fidelity.REDACTED, "inventory/categories.csv")
    duplicate = replace(dataset.columns[1], name=dataset.columns[0].name)
    changed = replace(dataset, columns=(dataset.columns[0], duplicate) + dataset.columns[2:])

    with pytest.raises(RegistryError, match="duplicate columns"):
        validate_dataset_contract(_replace_dataset(DATASETS, changed))


def test_dataset_source_paths_are_unique():
    dataset = _dataset(Fidelity.REDACTED, "inventory/categories.csv")
    duplicate = replace(dataset.columns[1], name="another_name", sources=("id",))
    changed = replace(dataset, columns=dataset.columns + (duplicate,))

    with pytest.raises(RegistryError, match="duplicate source paths"):
        validate_dataset_contract(_replace_dataset(DATASETS, changed))


def test_forward_coverage_detects_exported_model_without_dataset():
    changed = dict(DATASETS)
    changed.pop((Fidelity.REDACTED, "inventory/categories.csv"))

    with pytest.raises(RegistryError, match="exported-model dataset coverage"):
        validate_dataset_contract(changed)


def test_reverse_coverage_detects_unconsumed_output_promise():
    dataset = _dataset(Fidelity.REDACTED, "inventory/categories.csv")
    changed_dataset = replace(
        dataset,
        columns=tuple(column for column in dataset.columns if column.name != "name"),
    )

    with pytest.raises(RegistryError, match="unconsumed output promise"):
        validate_dataset_contract(_replace_dataset(DATASETS, changed_dataset))


@pytest.mark.parametrize("keyset", [("updated_at",), ("name",)])
def test_keyset_rejects_nullable_or_non_unique_members(keyset):
    dataset = _dataset(Fidelity.REDACTED, "inventory/categories.csv")
    if keyset == ("updated_at",):
        dataset = _dataset(Fidelity.REDACTED, "events/registrations.csv")
        keyset = ("host_waiver_accepted_at",)
    changed = replace(dataset, keyset=keyset)

    with pytest.raises(RegistryError, match="nullable keyset|not a total order"):
        validate_dataset_contract(_replace_dataset(DATASETS, changed))


def test_user_edge_completeness_detects_silent_edge():
    changed = dict(USER_EDGES)
    changed.pop((Fidelity.PORTABLE, "machines.ServiceRequestFile", "owner_user_id"))

    with pytest.raises(RegistryError, match="user-edge decisions"):
        validate_user_edges(changed)


def test_semantic_reference_completeness_detects_silent_json_key():
    changed = dict(SEMANTIC_REFERENCES)
    changed.pop((Fidelity.PORTABLE, "audit.AuditLog", "json:meta"))

    with pytest.raises(RegistryError, match="semantic-reference decisions"):
        validate_semantic_references(changed)


def test_global_user_projection_is_a_literal_non_growing_set():
    assert USER_PROJECTIONS == {
        Fidelity.REDACTED: frozenset({"id", "username"}),
        Fidelity.PORTABLE: frozenset(
            {
                "id",
                "username",
                "email",
                "first_name",
                "last_name",
                "display_name",
                "phone",
                "date_joined",
            }
        ),
    }
    for fidelity, expected in USER_PROJECTIONS.items():
        actual = {
            column.name
            for column in _dataset(fidelity, "global/users.csv").columns
        }
        assert actual == expected
