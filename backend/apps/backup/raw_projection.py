"""Raw-column fixture production with a bounded no-decrypt guard."""

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
import json
from threading import RLock
from unittest.mock import patch

from django.core import serializers
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import F
from django.db.models.fields.composite import CompositePrimaryKey
from django.utils.encoding import is_protected_type

from apps.encryption import crypto, mappers, services
from apps.encryption.registry import field_for


class RawProjectionViolation(RuntimeError):
    """A plaintext or model-instance path was reached during raw projection."""


_ACTIVE = ContextVar("backup_raw_projection_active", default=False)
_PATCH_LOCK = RLock()

# Cross-tenant reversal snapshots are selected alongside the row's own concrete
# columns. Values below are ORM paths, not model attributes read after materializing.
REFERENCE_COLUMNS = {
    "events.EventCollaborator": {
        "_event_makerspace_id": "event__makerspace_id",
        "_event_title": "event__title",
        "_event_starts_at": "event__starts_at",
        "_event_ends_at": "event__ends_at",
        "_makerspace_name": "makerspace__name",
        "_makerspace_slug": "makerspace__slug",
        "_event_makerspace_name": "event__makerspace__name",
        "_event_makerspace_slug": "event__makerspace__slug",
    },
    "events.EventRegistration": {
        "_registered_via_makerspace_name": "registered_via_makerspace__name",
        "_registered_via_makerspace_slug": "registered_via_makerspace__slug",
        "_payment_via_makerspace_name": "payment_via_makerspace__name",
        "_payment_via_makerspace_slug": "payment_via_makerspace__slug",
    },
    "operations.StockTransfer": {
        "_source_makerspace_name": "source_makerspace__name",
        "_source_makerspace_slug": "source_makerspace__slug",
        "_destination_makerspace_name": "destination_makerspace__name",
        "_destination_makerspace_slug": "destination_makerspace__slug",
    },
    "operations.StockTransferLine": {
        "_transfer_makerspace_id": "transfer__makerspace_id",
    },
    "payments.Payment": {
        "_via_makerspace_name": "via_makerspace__name",
        "_via_makerspace_slug": "via_makerspace__slug",
    },
}


class _RawValueProxy:
    """Give Django fields their usual value_to_string() interface without a model."""

    def __init__(self, record):
        self._record = record

    def __getattr__(self, name):
        try:
            return self._record[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def raw_records(queryset, model):
    """Read explicit concrete columns plus registered reversal snapshot columns."""
    columns = tuple(field.attname for field in model._meta.concrete_fields)
    annotations = {
        name: F(path) for name, path in REFERENCE_COLUMNS.get(model._meta.label, {}).items()
    }
    return list(queryset.values(*columns, **annotations))


def fixture_payload(model, records):
    """Build Django's ``{model, pk, fields}`` shape from raw mapping records."""
    unsupported = [
        field.name
        for field in model._meta.local_many_to_many
        if field.serialize and field.remote_field.through._meta.auto_created
    ]
    if unsupported:
        raise RawProjectionViolation(
            f"{model._meta.label} needs explicit raw through-table records for: "
            f"{', '.join(unsupported)}"
        )

    payload = []
    for record in records:
        proxy = _RawValueProxy(record)
        fields = {}
        for field in model._meta.local_fields:
            if field.serialize:
                fields[field.name] = _value_from_record(record, proxy, field)
        payload.append({
            "model": str(model._meta),
            "pk": _value_from_record(record, proxy, model._meta.pk),
            "fields": fields,
        })
    # Match serializers.serialize("json", ...), then the existing sorted re-dump.
    normalized = json.loads(json.dumps(payload, cls=DjangoJSONEncoder))
    return normalized


def _value_from_record(record, proxy, field):
    if isinstance(field, CompositePrimaryKey):
        return [_value_from_record(record, proxy, item) for item in field]
    value = record[field.attname]
    return value if is_protected_type(value) else field.value_to_string(proxy)


def _guarded_call(original, operation):
    def guarded(*args, **kwargs):
        if _ACTIVE.get():
            raise RawProjectionViolation(
                f"{operation} is forbidden during raw tenant projection."
            )
        return original(*args, **kwargs)

    return guarded


def _guarded_attribute(original):
    def guarded(instance, name):
        if _ACTIVE.get() and not name.startswith("_") and field_for(instance, name):
            raise RawProjectionViolation(
                f"Mapped PII attribute {type(instance)._meta.label}.{name} "
                "is forbidden during raw tenant projection."
            )
        return original(instance, name)

    return guarded


@contextmanager
def no_decrypt_guard():
    """Make plaintext/model projection paths fatal only in this bounded context."""
    with _PATCH_LOCK:
        token = _ACTIVE.set(True)
        try:
            with ExitStack() as stack:
                from apps.backup import tenant_projection

                targets = (
                    (crypto, "decrypt", "decrypt"),
                    (crypto, "decrypt_with_key_loader", "decrypt_with_key_loader"),
                    (services, "get_dek", "get_dek"),
                    (services, "unwrap_dek", "unwrap_dek"),
                    # Patch the names captured by ``from ... import`` in mappers too.
                    (mappers, "decrypt_with_key_loader", "mappers.decrypt_with_key_loader"),
                    (mappers, "get_dek", "mappers.get_dek"),
                    (serializers, "serialize", "Django serialization"),
                    (tenant_projection, "project_dataset", "legacy project_dataset"),
                    (mappers.ScopedPiiModelMixin, "save", "mapped model save"),
                )
                for owner, name, operation in targets:
                    original = getattr(owner, name)
                    stack.enter_context(
                        patch.object(owner, name, _guarded_call(original, operation))
                    )
                original_getattribute = mappers.ScopedPiiModelMixin.__getattribute__
                stack.enter_context(patch.object(
                    mappers.ScopedPiiModelMixin,
                    "__getattribute__",
                    _guarded_attribute(original_getattribute),
                ))
                yield
        finally:
            _ACTIVE.reset(token)
