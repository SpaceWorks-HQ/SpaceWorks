from apps.data_export.fields import EXTERNAL_REFERENCES
from apps.tenant_migration.schemas import EDGE_SCHEMAS


def test_every_external_reference_edge_has_exactly_one_snapshot_schema():
    assert set(EDGE_SCHEMAS) == EXTERNAL_REFERENCES
