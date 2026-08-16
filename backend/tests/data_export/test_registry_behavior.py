import pytest

from apps.data_export.datasets import DATASETS
from apps.data_export.references import (
    DanglingUserReferenceError,
    require_raw_user,
)
from apps.data_export.traversals import NON_TRAVERSABLE
from apps.data_export.types import Fidelity


@pytest.mark.parametrize(
    "dataset",
    DATASETS.values(),
    ids=lambda dataset: f"{dataset.fidelity}-{dataset.path}",
)
def test_each_dataset_predicate_excludes_foreign_tenant_rows(dataset):
    local_tenant = 101
    foreign_tenant = 202
    local = {path: local_tenant for path in dataset.predicate.any_paths}
    local.update(
        {path: local_tenant for path in dataset.predicate.local_or_global_paths}
    )
    foreign = {path: foreign_tenant for path in dataset.predicate.any_paths}
    foreign.update(
        {path: foreign_tenant for path in dataset.predicate.local_or_global_paths}
    )

    assert dataset.predicate.includes(local, local_tenant)
    assert not dataset.predicate.includes(foreign, local_tenant)


@pytest.mark.parametrize(
    "dataset",
    DATASETS.values(),
    ids=lambda dataset: f"{dataset.fidelity}-{dataset.path}",
)
def test_each_dataset_projection_cannot_read_a_foreign_tenant_value(dataset):
    foreign_value = f"FOREIGN::{dataset.path}::distinguishable"
    projected = []
    for column in dataset.columns:
        for source in column.sources:
            first_hop = source.split("__", 1)[0]
            crosses_foreign = (
                "__" in source
                and (dataset.model, first_hop) in NON_TRAVERSABLE
            )
            projected.append(foreign_value if crosses_foreign else f"LOCAL::{source}")

    assert foreign_value not in projected


def test_cross_tenant_shared_row_is_included_from_either_declared_perspective():
    dataset = DATASETS[(Fidelity.REDACTED, "transfers/transfers.csv")]
    tenant = 101

    for path in dataset.predicate.any_paths:
        values = {candidate: 202 for candidate in dataset.predicate.any_paths}
        values[path] = tenant
        assert dataset.predicate.includes(values, tenant)


def test_global_reference_dataset_selects_only_the_declared_closure():
    dataset = DATASETS[(Fidelity.REDACTED, "global/users.csv")]

    assert dataset.predicate.includes({"closure": 101}, 101)
    assert not dataset.predicate.includes({"closure": 202}, 101)


def test_portable_dangling_raw_user_reference_names_the_bad_row():
    with pytest.raises(
        DanglingUserReferenceError,
        match=r"machines.ServiceRequestFile row 44 has dangling owner_user_id=999",
    ):
        require_raw_user(
            Fidelity.PORTABLE,
            model="machines.ServiceRequestFile",
            row_pk=44,
            field="owner_user_id",
            user_id=999,
            existing_user_ids={1, 2},
        )


def test_redacted_raw_reference_stays_source_local_without_inventing_a_user():
    assert (
        require_raw_user(
            Fidelity.REDACTED,
            model="machines.ServiceRequestFile",
            row_pk=44,
            field="owner_user_id",
            user_id=999,
            existing_user_ids={1, 2},
        )
        == 999
    )
