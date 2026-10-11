import pytest
from django.apps import apps

from apps.data_export.classification import EXPORTED_MODEL_FIELDS
from apps.data_export.classification_w7_events import EVENT_EXPORTED_FIELDS, EVENT_OMITTED_FIELDS
from apps.data_export.fields import FIELDS
from apps.data_export.types import Fidelity, Omitted
from apps.tenant_migration.tenant_dump_field_snapshot import FIRST_PARTY_FIELD_NAMES
from apps.tenant_migration.target_projection_fields import TARGET_FIELD_PROJECTION


@pytest.mark.parametrize("label", sorted(EVENT_EXPORTED_FIELDS))
def test_event_ticketing_models_have_literal_export_and_projection_classification(label):
    actual = {field.name for field in apps.get_model(label)._meta.get_fields() if field.concrete or field.many_to_many}
    assert set(EXPORTED_MODEL_FIELDS[label].split()) == actual
    assert FIRST_PARTY_FIELD_NAMES[label] == actual


@pytest.mark.parametrize("edge", sorted(EVENT_OMITTED_FIELDS))
def test_code_and_contact_digests_never_export_and_get_fresh_target_defaults(edge):
    for fidelity in Fidelity:
        assert isinstance(FIELDS[(fidelity, *edge)], Omitted)
    rule = TARGET_FIELD_PROJECTION[edge]
    assert rule.use_model_default is True
    value = rule.resolved_value(*edge)
    assert value == "" if edge[1] == "email_digest" else len(value) == 64


@pytest.mark.parametrize("label", ["events.EventInvite", "events.EventPromoCode"])
def test_imported_event_codes_are_revoked(label):
    from django.utils import timezone
    assert TARGET_FIELD_PROJECTION[(label, "revoked_at")].resolved_value(label, "revoked_at") <= timezone.now()
