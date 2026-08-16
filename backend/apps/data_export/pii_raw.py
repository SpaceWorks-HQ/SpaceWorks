"""Raw scoped-PII projection for portable archives."""

import json
from pathlib import Path

from django.apps import apps

from apps.encryption import registry
from apps.encryption.crypto import is_envelope, parse_envelope

from .errors import ExportIntegrityError


def mapped_field_names(model_label):
    """Return the live registry's mapped fields for ``model_label``."""
    return tuple(field.field_name for field in registry.fields_for_label(model_label))


def raw_value(row, field_name):
    """Read the database column without invoking the model's decrypting accessor."""
    field = row._meta.get_field(field_name)
    try:
        return row.__dict__[field.attname]
    except KeyError as exc:
        raise ExportIntegrityError(
            f"{row._meta.label} row {row.pk} has deferred mapped field {field_name}."
        ) from exc


def aad_inputs(row, field_name):
    """Return every source-bound input needed to authenticate this field later."""
    mapped = next(
        (
            field
            for field in registry.fields_for_label(row._meta.label)
            if field.field_name == field_name
        ),
        None,
    )
    if mapped is None:
        raise ExportIntegrityError(
            f"{row._meta.label}.{field_name} is not a mapped PII field."
        )
    pk_attname = row._meta.pk.attname
    try:
        source_pk = row.__dict__[pk_attname]
    except KeyError as exc:
        raise ExportIntegrityError(
            f"{row._meta.label} has a deferred source primary key."
        ) from exc
    return {
        "makerspace_id": registry.makerspace_id_for(row, mapped),
        "table": row._meta.db_table,
        "pk": source_pk,
        "field": field_name,
    }


def select_related_paths(model_label):
    """Relationships required to resolve registry-declared AAD tenant paths."""
    paths = set()
    for field in registry.fields_for_label(model_label):
        path = field.makerspace_path or ""
        if path and path != "makerspace_id":
            parts = path.split(".")[:-1]
            if parts:
                paths.add("__".join(parts))
    return paths


class PiiAadCollector:
    """Validate portable envelopes and collect compact reconstruction metadata."""

    def __init__(self, makerspace_id):
        self.makerspace_id = makerspace_id
        self._models = {}

    def register_model(self, model_label):
        field_names = mapped_field_names(model_label)
        if not field_names:
            return
        model = apps.get_model(model_label)
        self._models.setdefault(
            model_label,
            {
                "label": model_label,
                "table": model._meta.db_table,
                "fields": sorted(field_names),
                "rows": {},
            },
        )

    def project(self, row, field_name):
        self.register_model(row._meta.label)
        value = raw_value(row, field_name)
        inputs = aad_inputs(row, field_name)
        if inputs["makerspace_id"] != self.makerspace_id:
            # A foreign tenant's key is the only key that could authenticate this
            # envelope. Emitting it would create a silently undecryptable archive.
            raise ExportIntegrityError(
                f"{row._meta.label} row {inputs['pk']} mapped field {field_name} "
                f"belongs to makerspace {inputs['makerspace_id']}, not "
                f"{self.makerspace_id}."
            )
        if value not in (None, ""):
            if not is_envelope(value):
                raise ExportIntegrityError(
                    f"{row._meta.label} row {inputs['pk']} mapped field "
                    f"{field_name} is not an encrypted PII envelope."
                )
            try:
                parse_envelope(value)
            except Exception as exc:
                raise ExportIntegrityError(
                    f"{row._meta.label} row {inputs['pk']} mapped field "
                    f"{field_name} has a malformed PII envelope."
                ) from exc
        entry = self._models[row._meta.label]
        entry["rows"][str(inputs["pk"])] = inputs["makerspace_id"]
        return value

    def write(self, root):
        path = Path(root, "pii", "aad_inputs.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"models": [self._models[label] for label in sorted(self._models)]}
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
