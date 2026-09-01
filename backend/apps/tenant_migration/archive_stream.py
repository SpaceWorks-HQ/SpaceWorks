"""Bounded readers and database-field coercion for decrypted PORTABLE archives."""

import csv
import json
from pathlib import Path

from django.db import models

from apps.data_export.datasets import DATASETS
from apps.data_export.types import Fidelity

from .insertion_errors import ArchiveFormatError


PORTABLE_DATASETS = {
    dataset.model: dataset
    for dataset in DATASETS.values()
    if dataset.fidelity is Fidelity.PORTABLE
}


class PortableArchive:
    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_dir():
            raise ArchiveFormatError("The decrypted archive directory does not exist.")

    def rows(self, model_label):
        dataset = PORTABLE_DATASETS.get(model_label)
        if dataset is None:
            raise ArchiveFormatError(f"No PORTABLE dataset exists for {model_label}.")
        path = self.root / dataset.path
        if not path.is_file():
            raise ArchiveFormatError(f"Archive dataset is missing: {dataset.path}.")
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            expected = {column.name for column in dataset.columns}
            actual = set(reader.fieldnames or ())
            if actual != expected:
                raise ArchiveFormatError(
                    f"Archive columns drifted for {model_label}; "
                    f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}."
                )
            yield from reader

    def json(self, relative_path):
        path = self.root / relative_path
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArchiveFormatError(f"Invalid archive JSON: {relative_path}.") from exc

    def json_lines(self, relative_path):
        path = self.root / relative_path
        if not path.is_file():
            raise ArchiveFormatError(f"Archive sidecar is missing: {relative_path}.")
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ArchiveFormatError(
                        f"Invalid JSON line in {relative_path}:{line_number}."
                    ) from exc


def database_value(field, raw):
    """Coerce one CSV cell without confusing a legal empty string with NULL."""
    if raw == "":
        if field.null:
            return None
        if isinstance(field, (models.CharField, models.TextField)):
            return ""
        if field.has_default():
            return field.get_default()
        raise ArchiveFormatError(
            f"{field.model._meta.label}.{field.name} cannot be empty."
        )
    if isinstance(field, models.JSONField):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ArchiveFormatError(
                f"Invalid JSON for {field.model._meta.label}.{field.name}."
            ) from exc
    if isinstance(field, models.BooleanField):
        # Decode exactly what the exporter encodes. `data_export/archive.py::csv_value`
        # writes booleans as lowercase "true"/"false", while Django's
        # `BooleanField.to_python` accepts "True"/"1"/"t" and rejects that spelling --
        # so delegating here silently fails on every boolean column in the archive.
        # Both halves of our own format must agree explicitly.
        if raw in ("true", "false"):
            return raw == "true"
        raise ArchiveFormatError(
            f"Invalid boolean for {field.model._meta.label}.{field.name}: {raw!r}."
        )
    try:
        return field.to_python(raw)
    except Exception as exc:
        raise ArchiveFormatError(
            f"Invalid value for {field.model._meta.label}.{field.name}."
        ) from exc
