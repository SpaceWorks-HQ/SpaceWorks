import pytest

from apps.data_export.classification import EXPORTED_MODELS, OMITTED_MODELS
from apps.data_export.references import RELATIONAL_USER_FIELDS
from apps.tenant_migration.tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from apps.tenant_migration.tenant_dump_types import ModelDisposition

pytestmark = pytest.mark.django_db


def test_history_is_classified_and_live_disclosure_controls_are_dropped():
    assert 'notifications.MemberBroadcast' in EXPORTED_MODELS
    assert ('notifications.MemberBroadcast', 'created_by') in RELATIONAL_USER_FIELDS
    for label in ('bookings.BookingCalendarFeed', 'integrations.NotificationTimingPolicy'):
        assert label in OMITTED_MODELS
        assert FIRST_PARTY_MODEL_RULES[label].disposition == ModelDisposition.DROP


def test_export_and_field_catalog_guards_cover_wp3_schema():
    from apps.data_export.guards import validate_all
    from apps.tenant_migration.tenant_dump_catalog import validate_catalog
    validate_all()
    # The coordinator re-pins the combined schema checksum; this lane still checks
    # every literal model/field policy against its actual migration graph.
    from apps.tenant_migration.tenant_dump_catalog import schema_digest
    validate_catalog(expected_schema_digest=schema_digest())
