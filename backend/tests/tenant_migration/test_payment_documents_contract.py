"""PaymentDocument remains core, portable and capture-bound financial history."""

from types import SimpleNamespace

import pytest

from apps.data_export.classification import EXPORTED_MODEL_FIELDS
from apps.data_export.datasets import DATASET_SPECS
from apps.data_export.guards import validate_all
from apps.data_export.references import RELATIONAL_USER_FIELDS
from apps.tenant_migration.money_digest import MoneyDriftRefused, assert_money_unchanged, money_fingerprint
from apps.tenant_migration.projection_guards import validate_unique_constraint_risks
from apps.tenant_migration.tenant_dump_authority import AUTHORITY_FIELD_OVERRIDES
from apps.tenant_migration.tenant_dump_field_snapshot import FIRST_PARTY_FIELD_NAMES
from apps.tenant_migration.tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from apps.tenant_migration.tenant_dump_types import ModelDisposition, AuthorityDisposition
from tests.payments.test_documents import settled
from apps.payments.models import MakerspaceBillingSettings

pytestmark = pytest.mark.django_db


def test_document_model_has_complete_portable_field_user_and_ownership_declarations():
    label = "payments.PaymentDocument"
    validate_all()
    validate_unique_constraint_risks()
    assert label in DATASET_SPECS
    assert set(EXPORTED_MODEL_FIELDS[label].split()) == FIRST_PARTY_FIELD_NAMES[label]
    assert FIRST_PARTY_MODEL_RULES[label].disposition == ModelDisposition.PROJECT
    assert (label, "issued_by") in RELATIONAL_USER_FIELDS
    for field in FIRST_PARTY_FIELD_NAMES[label]:
        assert AuthorityDisposition.PRESERVE in AUTHORITY_FIELD_OVERRIDES[(label, field)].dispositions


def test_counter_or_prefix_changed_after_capture_refuses_publication():
    space, _, _ = settled("portable-documents")
    capture = SimpleNamespace(source_makerspace_id=space.pk, money_fingerprint_sha256=money_fingerprint(space.pk))
    policy = MakerspaceBillingSettings.objects.get(makerspace=space)
    policy.number_prefix = "AFTER-CAPTURE-"
    policy.save()
    with pytest.raises(MoneyDriftRefused):
        assert_money_unchanged(capture)


@pytest.mark.parametrize("field,value", [("number_prefix", "NEW-"), ("next_document_number", 4)])
def test_numbering_policy_drift_is_detected_before_first_document(field, value):
    from tests.return_helpers import make_space
    space = make_space("empty-document-fingerprint")
    policy = MakerspaceBillingSettings.objects.create(makerspace=space)
    capture = SimpleNamespace(source_makerspace_id=space.pk, money_fingerprint_sha256=money_fingerprint(space.pk))
    setattr(policy, field, value)
    policy.save(update_fields=[field])
    with pytest.raises(MoneyDriftRefused):
        assert_money_unchanged(capture)
