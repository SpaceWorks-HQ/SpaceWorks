import pytest

from apps.boxes.models import QrCode
from apps.data_export.models import MODELS
from apps.payments.models import Payment
from apps.tenant_migration.reference_guards import (
    ReferenceRegistryError,
    retained_relations_to_omitted_models,
    validate_discriminator_references,
    validate_omitted_target_relations,
    validate_payment_subject_references,
    validate_raw_scalar_references,
    validate_reference_registry,
)
from apps.tenant_migration.audit_reference_guards import (
    discover_audit_meta_references,
    validate_audit_meta_references,
)
from apps.tenant_migration.audit_references import (
    AUDIT_META_REFERENCES,
    AUDIT_TARGET_DISPOSITIONS,
    AuditReferenceDisposition,
    normalize_audit_target_type,
)
from apps.tenant_migration.references import (
    DISCRIMINATOR_REFERENCES,
    OMITTED_TARGET_RELATIONS,
    PAYMENT_SUBJECT_REFERENCES,
    RAW_SCALAR_REFERENCES,
)


def test_complete_reference_registry_is_valid():
    validate_reference_registry()


def test_every_storable_discriminator_value_is_model_specific():
    qr_values = set(QrCode.TargetType.values)
    qr_targets = DISCRIMINATOR_REFERENCES[
        ("boxes.QrCode", "target_type", "target_id")
    ]
    loan_targets = DISCRIMINATOR_REFERENCES[
        ("hardware_requests.PublicToolLoan", "target_type", "target_id")
    ]
    batch_targets = DISCRIMINATOR_REFERENCES[
        ("operations.QrPrintBatchItem", "target_type", "target_id")
    ]

    assert set(qr_targets) == qr_values
    assert set(batch_targets) == qr_values
    assert set(loan_targets) == qr_values | {"direct"}
    assert "direct" not in qr_targets
    assert loan_targets["direct"] == "hardware_requests.HardwareRequest"


def test_discriminator_guard_rejects_a_removed_value():
    changed = {edge: dict(targets) for edge, targets in DISCRIMINATOR_REFERENCES.items()}
    changed[("hardware_requests.PublicToolLoan", "target_type", "target_id")].pop(
        "direct"
    )

    with pytest.raises(ReferenceRegistryError, match="discriminator values"):
        validate_discriminator_references(changed)


def test_payment_subject_guard_rejects_a_removed_enum_value():
    changed = dict(PAYMENT_SUBJECT_REFERENCES)
    changed.pop(Payment.SubjectType.BOOKING)

    with pytest.raises(ReferenceRegistryError, match="Payment.SubjectType values"):
        validate_payment_subject_references(changed)


def test_omitted_target_guard_is_total_and_rejects_a_removed_rule():
    assert retained_relations_to_omitted_models() == {
        ("presence.PresenceSession", "created_via_claim_session")
    }
    changed = dict(OMITTED_TARGET_RELATIONS)
    changed.pop(("presence.PresenceSession", "created_via_claim_session"))

    with pytest.raises(ReferenceRegistryError, match="retained relations"):
        validate_omitted_target_relations(changed)


def test_raw_user_guard_rejects_a_removed_disposition():
    changed = dict(RAW_SCALAR_REFERENCES)
    changed.pop(("machines.ServiceRequestFile", "owner_user_id"))

    with pytest.raises(ReferenceRegistryError, match="raw scalar references"):
        validate_raw_scalar_references(changed)


def test_audit_meta_guard_rejects_a_removed_dictionary_key_declaration():
    changed = dict(AUDIT_META_REFERENCES)
    changed.pop(("request.accepted", "accepted.<keys>"))

    with pytest.raises(ReferenceRegistryError, match="audit meta ID paths"):
        validate_audit_meta_references(changed)


def test_audit_meta_guard_rejects_a_new_id_bearing_key(tmp_path):
    source = tmp_path / "producer.py"
    source.write_text(
        'from apps.audit import services as audit\n'
        'audit.record(actor, "future.action", meta={"future_id": object.pk})\n',
        encoding="utf-8",
    )
    discovery = discover_audit_meta_references(tmp_path)

    with pytest.raises(ReferenceRegistryError, match="future_id"):
        validate_audit_meta_references(AUDIT_META_REFERENCES, discovery=discovery)


def test_audit_target_registry_is_derived_from_export_model_labels():
    assert set(AUDIT_TARGET_DISPOSITIONS) == {
        normalize_audit_target_type(label) for label in MODELS
    }
    assert AUDIT_TARGET_DISPOSITIONS["inventory.inventoryproduct"].disposition is (
        AuditReferenceDisposition.REMAP
    )
    assert AUDIT_TARGET_DISPOSITIONS["accounts.user"].kind == "audit_user_target"
    assert AUDIT_TARGET_DISPOSITIONS["accounts.memberclaimcode"].kind == (
        "audit_omitted_target_model"
    )


def test_ast_discovery_reports_dynamic_actions_and_non_literal_meta():
    unresolved = discover_audit_meta_references().unresolvable
    assert any(item.reason == "dynamic action" for item in unresolved)
    assert any(item.reason == "non-literal meta" for item in unresolved)
