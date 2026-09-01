import pytest
from django.core.exceptions import ValidationError

from apps.data_export.fields import EXTERNAL_REFERENCES
from apps.tenant_migration.closure_references import (
    CROSS_TENANT_DEPENDENT_REFERENCES,
    MOVABLE_DISCRIMINATOR_REFERENCES,
    MOVABLE_LIST_REFERENCES,
    MOVABLE_ROW_REFERENCES,
)
from apps.tenant_migration.schemas import EDGE_SCHEMAS, validate_snapshot


def test_every_external_reference_edge_has_exactly_one_snapshot_schema():
    discriminator_edges = {
        (model_label, "target_type+target_id")
        for model_label, _type_field, _id_field in MOVABLE_DISCRIMINATOR_REFERENCES
    }
    closure_edges = (
        set(MOVABLE_ROW_REFERENCES)
        | set(MOVABLE_LIST_REFERENCES)
        | discriminator_edges
        | set(CROSS_TENANT_DEPENDENT_REFERENCES)
    )
    assert set(EDGE_SCHEMAS) == EXTERNAL_REFERENCES | closure_edges


@pytest.mark.parametrize("edge", sorted(EDGE_SCHEMAS))
def test_no_edge_accepts_a_null_snapshot(edge):
    """A null reference produces no snapshot at all, so null must never validate.

    The export records provenance only for a reference that exists and belongs to
    another makerspace. If a null ever reaches here, a snapshot builder returned
    nothing where it should have returned a foreign row's detail -- which is a bug
    the schema should catch rather than wave through.
    """
    with pytest.raises(ValidationError, match="must be an object"):
        validate_snapshot(edge[0], edge[1], None)


def test_a_nested_object_is_required_too():
    with pytest.raises(ValidationError, match="must be an object"):
        validate_snapshot(
            "operations.StockTransfer",
            "source_container",
            {"label": "Unowned container", "makerspace": None},
        )
