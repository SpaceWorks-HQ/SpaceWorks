"""Consume the non-FK reference registries during final-row construction."""

import re

from django.apps import apps

from .audit_references import AuditReferenceDisposition
from .references import (
    AUDIT_META_REFERENCES,
    AUDIT_TARGET_DISPOSITIONS,
    DISCRIMINATOR_REFERENCES,
    NOTIFICATION_URL_ROUTES,
    PAYMENT_SUBJECT_REFERENCES,
    normalize_audit_target_type,
)


def remap_semantic_references(label, source, row, pk_map, references):
    if label in {edge[0] for edge in DISCRIMINATOR_REFERENCES}:
        _remap_discriminator(label, row, pk_map)
    if label == "payments.Payment":
        if references.get(label, source["id"], "subject_id"):
            return False
        target = apps.get_model(PAYMENT_SUBJECT_REFERENCES[row["subject_type"]])
        row["subject_id"] = pk_map.lookup(target, row["subject_id"])
    elif label == "audit.AuditLog":
        _remap_audit(row, pk_map)
    elif label == "notifications.Notification":
        row["url_path"] = _remap_notification_url(row["url_path"], pk_map)
    elif label == "hardware_requests.PublicToolLoan":
        row["asset_ids"] = _remap_list("inventory.InventoryAsset", row["asset_ids"], pk_map)
        row["qr_ids"] = _remap_list("boxes.QrCode", row["qr_ids"], pk_map)
    elif label == "machines.ServiceRequestFile" and row["owner_user_id"] is not None:
        row["owner_user_id"] = pk_map.lookup(
            apps.get_model("accounts.User"), row["owner_user_id"]
        )
    elif label == "tenant_migration.ExternalTenantReference" and row["target_object_id"]:
        target = apps.get_model(row["target_model_label"])
        row["target_object_id"] = str(pk_map.lookup(target, row["target_object_id"]))
    return True


def _remap_discriminator(label, row, pk_map):
    declarations = DISCRIMINATOR_REFERENCES[(label, "target_type", "target_id")]
    target_label = declarations[row["target_type"]]
    row["target_id"] = pk_map.lookup(apps.get_model(target_label), row["target_id"])


def _remap_list(label, values, pk_map):
    model = apps.get_model(label)
    return [pk_map.lookup(model, value) for value in (values or [])]


def _remap_audit(row, pk_map):
    # Importing source actor IDs as live target actors would forge immutable audit
    # attribution. The source username column remains archive evidence only.
    row["actor_id"] = None
    disposition = AUDIT_TARGET_DISPOSITIONS.get(
        normalize_audit_target_type(row["target_type"])
    )
    if row["target_id"] and disposition and (
        disposition.disposition is AuditReferenceDisposition.REMAP
    ):
        model = apps.get_model(disposition.target_model_label)
        row["target_id"] = str(pk_map.lookup(model, row["target_id"]))
    row["meta"] = _remap_audit_dict(row["action"], row["meta"], pk_map, "")


def _remap_audit_dict(action, value, pk_map, prefix):
    if not isinstance(value, dict):
        return value
    output = {}
    key_rule = AUDIT_META_REFERENCES.get((action, f"{prefix}.<keys>")) if prefix else None
    for key, child in value.items():
        output_key = _remap_audit_value(key_rule, key, pk_map) if key_rule else key
        path = f"{prefix}.{key}" if prefix else str(key)
        rule = AUDIT_META_REFERENCES.get((action, path))
        if rule:
            child = _remap_audit_value(rule, child, pk_map)
        elif isinstance(child, dict):
            child = _remap_audit_dict(action, child, pk_map, path)
        output[str(output_key)] = child
    return output


def _remap_audit_value(rule, value, pk_map):
    if rule.disposition is not AuditReferenceDisposition.REMAP or value is None:
        return value
    model = apps.get_model(rule.target_model_label)
    if isinstance(value, list):
        return [pk_map.lookup(model, item) for item in value]
    return pk_map.lookup(model, value)


def _remap_notification_url(value, pk_map):
    for route in NOTIFICATION_URL_ROUTES:
        match = re.fullmatch(route.pattern, value or "")
        if match:
            target = pk_map.lookup(
                apps.get_model(route.target_model_label), match.group("object_id")
            )
            return value[: match.start("object_id")] + str(target) + value[match.end("object_id") :]
    return ""
