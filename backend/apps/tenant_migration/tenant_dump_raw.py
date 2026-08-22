"""Reviewed raw-column transport and authority sanitization for Lane D."""

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json

from django.apps import apps
from django.core.serializers.json import DjangoJSONEncoder

from apps.encryption.registry import fields_for

from .tenant_dump_catalog import FIELD_POLICIES, TenantDumpCatalogError, catalog_models
from .tenant_dump_field_snapshot import (
    AUTO_CREATED_FIELD_NAMES,
    FIRST_PARTY_FIELD_NAMES,
    THIRD_PARTY_FIELD_NAMES,
    UNMANAGED_FIELD_NAMES,
)
from .tenant_dump_types import AuthorityDisposition, AuthorityField


def _reviewed_allowlists():
    """Translate the literal D1 field snapshot to physical raw column names."""
    snapshots = {
        **FIRST_PARTY_FIELD_NAMES,
        **AUTO_CREATED_FIELD_NAMES,
        **THIRD_PARTY_FIELD_NAMES,
        **UNMANAGED_FIELD_NAMES,
    }
    result = {}
    for model in catalog_models():
        reviewed = snapshots[model._meta.label]
        result[model._meta.label] = frozenset(
            field.attname
            for field in model._meta.concrete_fields
            if field.name in reviewed
        )
    return result


# The source-controlled D1 snapshot is the review surface. This translated fixture is
# deliberately fixed at import and checked back against the live concrete field graph.
RAW_COLUMN_ALLOWLISTS = _reviewed_allowlists()


def validate_raw_column_allowlists(*, models=None, allowlists=None):
    models = tuple(models or catalog_models())
    allowlists = RAW_COLUMN_ALLOWLISTS if allowlists is None else allowlists
    actual = {
        model._meta.label: frozenset(
            field.attname for field in model._meta.concrete_fields
        )
        for model in models
    }
    declared = {label: frozenset(columns) for label, columns in allowlists.items()}
    if declared != actual:
        missing_labels = sorted(set(actual) - set(declared))
        extra_labels = sorted(set(declared) - set(actual))
        changed = sorted(
            label
            for label in set(actual) & set(declared)
            if actual[label] != declared[label]
        )
        raise TenantDumpCatalogError(
            "Lane D raw-column allowlist drifted; "
            f"missing_labels={missing_labels}, extra_labels={extra_labels}, "
            f"changed={changed}"
        )


def assert_raw_record(model, record):
    expected = RAW_COLUMN_ALLOWLISTS[model._meta.label]
    supplied = {name for name in record if not name.startswith("_")}
    if supplied != expected:
        raise TenantDumpCatalogError(
            f"Lane D raw row drifted for {model._meta.label}; "
            f"missing={sorted(expected - supplied)}, extra={sorted(supplied - expected)}"
        )


@dataclass(frozen=True)
class SanitizedRow:
    model: object
    source_pk: object
    values: Mapping[str, object]

    @property
    def identity(self):
        return self.model._meta.label, self.source_pk


def sanitize_record(
    model,
    source,
    *,
    disposition_selector: Callable | None = None,
):
    """Return a complete physical row without reading a model attribute."""
    assert_raw_record(model, source)
    values = {}
    for field in model._meta.concrete_fields:
        value = source[field.attname]
        rule = FIELD_POLICIES[(model._meta.label, field.name)]
        disposition = _selected_disposition(
            model, field, source, rule, disposition_selector
        )
        if disposition in {AuthorityDisposition.RESET, AuthorityDisposition.DROP}:
            value = _reset_value(model, field, source)
        values[field.column] = deepcopy(value)
    return SanitizedRow(
        model=model,
        source_pk=source[model._meta.pk.attname],
        values=values,
    )


def _selected_disposition(model, field, source, rule, selector):
    if not isinstance(rule, AuthorityField):
        return AuthorityDisposition.PRESERVE
    if len(rule.dispositions) == 1:
        return rule.dispositions[0]
    if selector is not None:
        selected = selector(model._meta.label, field.name, source, rule)
        if selected not in rule.dispositions:
            raise TenantDumpCatalogError(
                f"Invalid conditional disposition for {model._meta.label}.{field.name}."
            )
        return selected
    # D1 source filtering has already retained only the preserving branch for these
    # mixed row predicates. Identity-stub selection supplies an explicit selector.
    if AuthorityDisposition.PRESERVE in rule.dispositions:
        return AuthorityDisposition.PRESERVE
    raise TenantDumpCatalogError(
        f"Lane D row predicate was not selected for {model._meta.label}.{field.name}."
    )


def _reset_value(model, field, source):
    from .target_projection import TARGET_FIELD_PROJECTION

    target = TARGET_FIELD_PROJECTION.get((model._meta.label, field.name))
    if target is not None and (
        target.condition is None
        or source.get(target.condition[0]) == target.condition[1]
    ):
        return target.resolved_value(model._meta.label, field.name)
    explicit = {
        ("accounts.User", "is_superuser"): False,
        ("accounts.User", "is_staff"): False,
        ("accounts.User", "role"): "requester",
        ("accounts.User", "telegram_user_id"): "",
        ("accounts.User", "external_checkin_user_id"): "",
        ("makerspaces.Makerspace", "lifecycle_state"): "importing",
        ("makerspaces.Makerspace", "archived_by"): None,
        ("makerspaces.Makerspace", "cors_allowed_origins"): [],
        ("makerspaces.Makerspace", "smtp_password"): "",
        ("makerspaces.Makerspace", "telegram_bot_token"): "",
        ("makerspaces.Makerspace", "slack_webhook_url"): "",
        ("makerspaces.Makerspace", "mattermost_webhook_url"): "",
        ("makerspaces.Makerspace", "discord_webhook_url"): "",
        ("audit.AuditLog", "event_uuid"): None,
        ("audit.AuditLog", "row_mac"): None,
    }
    key = (model._meta.label, field.name)
    if key in explicit:
        return deepcopy(explicit[key])
    if field.has_default():
        return field.get_default()
    if field.null:
        return None
    if getattr(field, "empty_strings_allowed", False):
        return ""
    raise TenantDumpCatalogError(
        f"Lane D has no safe reset value for {model._meta.label}.{field.name}."
    )


def mapped_raw_digest(rows_by_label):
    """Digest ciphertext/plaintext columns without parsing either representation."""
    digest = hashlib.sha256()
    for label in sorted(rows_by_label):
        model = apps.get_model(label)
        mapped = fields_for(model)
        if not mapped:
            continue
        pk_name = model._meta.pk.attname
        for row in sorted(rows_by_label[label], key=lambda item: str(item[pk_name])):
            for item in sorted(mapped, key=lambda value: value.field_name):
                value = row[model._meta.get_field(item.field_name).attname]
                payload = json.dumps(
                    value,
                    cls=DjangoJSONEncoder,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                for component in (label.encode(), str(row[pk_name]).encode(), item.field_name.encode(), payload):
                    digest.update(len(component).to_bytes(8, "big"))
                    digest.update(component)
    return digest.hexdigest()


class _RawDigestEncoder(DjangoJSONEncoder):
    def default(self, value):
        if isinstance(value, (bytes, bytearray, memoryview)):
            return {"__bytes__": bytes(value).hex()}
        return super().default(value)


def projected_raw_digest(rows_by_label):
    """Canonical digest of every explicitly selected concrete source row."""
    digest = hashlib.sha256()
    for label in sorted(rows_by_label):
        model = apps.get_model(label)
        pk_name = model._meta.pk.attname
        for row in sorted(rows_by_label[label], key=lambda item: str(item[pk_name])):
            payload = json.dumps(
                row,
                cls=_RawDigestEncoder,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            label_bytes = label.encode("utf-8")
            digest.update(len(label_bytes).to_bytes(8, "big"))
            digest.update(label_bytes)
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
    return digest.hexdigest()
