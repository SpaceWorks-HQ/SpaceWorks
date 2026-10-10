import pytest

from apps.data_export.guards import validate_all
from apps.data_export.datasets import DATASET_SPECS
from apps.data_export.models import OMITTED_MODELS
from apps.data_export.references_core import RELATIONAL_USER_FIELDS
from apps.backup.archive_payload import NON_OBJECT_KEY_FIELDS
from apps.tenant_migration.authority_guards import validate_authority_registry
from apps.tenant_migration.projection_guards import validate_projection_registry
from apps.tenant_migration.source_gate_guards import validate_source_gate_coverage
from apps.tenant_migration.target_projection_rows import ROW_POLICIES
from apps.tenant_migration.target_projection_types import RowDisposition

pytestmark = pytest.mark.django_db


def test_new_models_fields_user_edges_projection_and_source_gate_catalogues_are_complete():
    validate_all()
    validate_authority_registry()
    validate_projection_registry()
    validate_source_gate_coverage()
    assert "notifications.MemberNotificationPreference" in DATASET_SPECS
    assert "notifications.NotificationInboxRow" in OMITTED_MODELS
    assert "integrations.EmailSuppression" in OMITTED_MODELS
    assert ("notifications.NotificationInboxRow", "event_key") in NON_OBJECT_KEY_FIELDS
    for label, field in (("notifications.NotificationInboxRow", "user"),
                         ("notifications.MemberNotificationPreference", "user"),
                         ("integrations.EmailSuppression", "created_by"),
                         ("integrations.EmailLog", "recipient")):
        assert (label, field) in RELATIONAL_USER_FIELDS
    for label in ("notifications.MemberNotificationPreference", "notifications.NotificationInboxRow",
                  "integrations.EmailSuppression"):
        assert ROW_POLICIES[label].disposition is RowDisposition.DROP
