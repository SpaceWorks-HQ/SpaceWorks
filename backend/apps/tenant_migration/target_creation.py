"""Create the target tenant from source content plus target-owned projection."""

from django.utils.crypto import get_random_string

from apps.makerspaces.models import Makerspace

from .archive_stream import database_value
from .omitted_fields import OMITTED_FIELD_RECONSTRUCTIONS, OmittedFieldDisposition
from .target_projection import TARGET_FIELD_PROJECTION


def create_target_makerspace(archive, job, *, target_identity=None):
    source = next(archive.rows("makerspaces.Makerspace"))
    identity = dict(target_identity or {})
    unknown = set(identity) - {"name", "slug"}
    if unknown:
        raise ValueError(f"Unsupported target identity fields: {sorted(unknown)}.")
    values = {}
    for field in Makerspace._meta.local_concrete_fields:
        if field.primary_key or field.name in {"created_by", "archived_by"}:
            continue
        if field.attname in source:
            values[field.name] = database_value(field, source[field.attname])
        else:
            values[field.name] = _omitted_value(field)
    for (label, name), policy in TARGET_FIELD_PROJECTION.items():
        if label == "makerspaces.Makerspace":
            values[name] = policy.resolved_value(label, name)
    values.update(identity)
    values["created_by"] = None
    values["archived_by"] = None
    values["slug"] = _available_slug(values["slug"], job)
    if Makerspace.objects.filter(public_code=values["public_code"]).exists():
        values["public_code"] = _fresh_value(Makerspace._meta.get_field("public_code"))
    return Makerspace.objects.create(**values)


def _omitted_value(field):
    disposition = OMITTED_FIELD_RECONSTRUCTIONS[("makerspaces.Makerspace", field.name)]
    if disposition is OmittedFieldDisposition.FRESH:
        return _fresh_value(field)
    if disposition is OmittedFieldDisposition.DERIVED:
        return field.get_default()
    if disposition is OmittedFieldDisposition.EMPTY_STRING:
        return ""
    if disposition is OmittedFieldDisposition.NULL:
        return None
    raise ValueError(f"Unsupported Makerspace reconstruction for {field.name}.")


def _available_slug(source_slug, job):
    if not Makerspace.objects.filter(slug=source_slug).exists():
        return source_slug
    base = f"{source_slug}-import-{str(job.pk)[:8]}"[:100].rstrip("-")
    if not Makerspace.objects.filter(slug=base).exists():
        return base
    return f"{base[:91]}-{get_random_string(8).lower()}"


def _fresh_value(field):
    for _attempt in range(16):
        value = field.get_default()
        if not field.model._base_manager.filter(**{field.name: value}).exists():
            return value
    raise RuntimeError(
        f"Could not generate a unique value for {field.model._meta.label}.{field.name}."
    )
