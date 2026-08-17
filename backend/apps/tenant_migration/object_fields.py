"""Rewrite portable object references to their preassigned target keys."""

from .insertion_errors import ArchiveFormatError


PRIVATE_FIELDS = frozenset({"object_key"})
PUBLIC_FIELDS = frozenset({"image_key", "avatar_key", "logo_key", "cover_image_key"})
OBJECT_FIELDS = PRIVATE_FIELDS | PUBLIC_FIELDS


def rewrite_object_fields(model, row, object_key_map):
    for field in model._meta.local_concrete_fields:
        if field.name not in OBJECT_FIELDS:
            continue
        source_key = row.get(field.column)
        if not source_key:
            continue
        try:
            row[field.column] = object_key_map[str(source_key)]
        except KeyError as exc:
            raise ArchiveFormatError(
                f"Archive object manifest does not account for {source_key!r}."
            ) from exc


def bucket_kind_for_field(field_name):
    if field_name in PRIVATE_FIELDS:
        return "private"
    if field_name in PUBLIC_FIELDS:
        return "public_image"
    return None
