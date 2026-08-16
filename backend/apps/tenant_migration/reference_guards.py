"""Total drift checks for non-FK tenant-import reference semantics."""

import re

from django.apps import apps

from apps.data_export.fields import FIELDS
from apps.data_export.models import EXPORTED_MODELS, MODELS
from apps.data_export.references import POLYMORPHIC_PAIRS, RAW_USER_REFERENCE_FIELDS
from apps.data_export.types import Fidelity, Omitted, OmittedModel

from .references import (
    DISCRIMINATOR_REFERENCES,
    NOTIFICATION_URL_ROUTES,
    OMITTED_TARGET_RELATIONS,
    PAYMENT_SUBJECT_REFERENCES,
    RAW_SCALAR_REFERENCES,
    UNRECOGNISED_NOTIFICATION_URL,
    ClearWithProvenance,
    NullWithProvenance,
)


class ReferenceRegistryError(AssertionError):
    pass


def validate_reference_registry(
    *,
    discriminator_references=DISCRIMINATOR_REFERENCES,
    raw_scalar_references=RAW_SCALAR_REFERENCES,
    omitted_target_relations=OMITTED_TARGET_RELATIONS,
    payment_subject_references=PAYMENT_SUBJECT_REFERENCES,
    notification_url_routes=NOTIFICATION_URL_ROUTES,
):
    validate_discriminator_references(discriminator_references)
    validate_raw_scalar_references(raw_scalar_references)
    validate_omitted_target_relations(omitted_target_relations)
    validate_payment_subject_references(payment_subject_references)
    validate_notification_url_routes(notification_url_routes)


def validate_discriminator_references(declarations=DISCRIMINATOR_REFERENCES):
    qr_model = apps.get_model("boxes.QrCode")
    qr_values = set(qr_model.TargetType.values)
    expected = {
        ("boxes.QrCode", "target_type", "target_id"): qr_values,
        ("hardware_requests.PublicToolLoan", "target_type", "target_id"): qr_values
        | {"direct"},
        ("operations.QrPrintBatchItem", "target_type", "target_id"): qr_values,
    }
    discovered_pairs = {
        (label, "target_type", "target_id")
        for label, location in POLYMORPHIC_PAIRS
        if label != "audit.AuditLog" and location == "target_type+target_id"
    }
    _equal("discriminator reference pairs", set(declarations), discovered_pairs)
    for edge, expected_values in expected.items():
        _equal(f"{edge[0]} discriminator values", set(declarations[edge]), expected_values)
        _validate_model_labels(declarations[edge].values())


def validate_raw_scalar_references(declarations=RAW_SCALAR_REFERENCES):
    expected = {
        edge for edge in RAW_USER_REFERENCE_FIELDS if edge[0] in EXPORTED_MODELS
    }
    _equal("exported raw scalar references", set(declarations), expected)
    for disposition in declarations.values():
        if disposition.target_model_label != "accounts.User":
            raise ReferenceRegistryError("raw user reference must use the accounts.User PK map")


def retained_relations_to_omitted_models():
    edges = set()
    for label in EXPORTED_MODELS:
        model = apps.get_model(label)
        for field in model._meta.get_fields():
            if not (field.concrete and field.is_relation and field.related_model):
                continue
            target_label = field.related_model._meta.label
            if not isinstance(MODELS.get(target_label), OmittedModel):
                continue
            disposition = FIELDS[(Fidelity.PORTABLE, label, field.name)]
            if not isinstance(disposition, Omitted):
                edges.add((label, field.name))
    return edges


def validate_omitted_target_relations(declarations=OMITTED_TARGET_RELATIONS):
    actual = retained_relations_to_omitted_models()
    _equal("retained relations to omitted models", set(declarations), actual)
    for edge, disposition in declarations.items():
        field = apps.get_model(edge[0])._meta.get_field(edge[1])
        if not isinstance(disposition, NullWithProvenance) or not field.null:
            raise ReferenceRegistryError(f"{edge[0]}.{edge[1]} needs a legal null rule")
        if field.related_model._meta.label != disposition.target_model_label:
            raise ReferenceRegistryError(f"{edge[0]}.{edge[1]} target model drifted")


def validate_payment_subject_references(declarations=PAYMENT_SUBJECT_REFERENCES):
    payment = apps.get_model("payments.Payment")
    _equal("Payment.SubjectType values", set(declarations), set(payment.SubjectType.values))
    _validate_model_labels(declarations.values())


def validate_notification_url_routes(routes=NOTIFICATION_URL_ROUTES):
    if not isinstance(UNRECOGNISED_NOTIFICATION_URL, ClearWithProvenance):
        raise ReferenceRegistryError(
            "unrecognised notification URLs need an explicit clear rule"
        )
    for route in routes:
        try:
            compiled = re.compile(route.pattern)
        except re.error as exc:
            raise ReferenceRegistryError(
                f"invalid notification URL pattern: {route.pattern}"
            ) from exc
        if "object_id" not in compiled.groupindex:
            raise ReferenceRegistryError("notification URL pattern needs an object_id group")
        _validate_model_labels((route.target_model_label,))


def _validate_model_labels(labels):
    for label in labels:
        if label not in EXPORTED_MODELS and label != "accounts.User":
            raise ReferenceRegistryError(f"reference target is not exported: {label}")
        apps.get_model(label)


def _equal(subject, declared, actual):
    if declared != actual:
        raise ReferenceRegistryError(
            f"{subject} drifted; missing={sorted(actual - declared)}, "
            f"extra={sorted(declared - actual)}"
        )
