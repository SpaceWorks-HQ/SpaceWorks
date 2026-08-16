"""PORTABLE reference validation and typed inert-provenance output."""

import json
import re
from collections import defaultdict
from pathlib import Path

from django.apps import apps

from apps.separability.registry import runtime_active

from .datasets import DATASETS
from .errors import ExportIntegrityError
from .types import Fidelity


class ReferenceProvenanceWriter:
    """Validate semantic IDs and append provenance in archive row order."""

    def __init__(self, root, makerspace_id):
        if not runtime_active("tenant_migration"):
            raise ExportIntegrityError("PORTABLE export requires the tenant_migration module.")

        # Keep all migration-only imports behind the runtime guard. A deployment may
        # tombstone tenant_migration and must still be able to build REDACTED exports.
        from apps.tenant_migration.reference_guards import validate_reference_registry
        from apps.tenant_migration.references import (
            DISCRIMINATOR_REFERENCES,
            NOTIFICATION_URL_ROUTES,
            OMITTED_TARGET_RELATIONS,
            ORPHANED_PAYMENT_SUBJECT_KIND,
            PAYMENT_SUBJECT_REFERENCES,
            UNRECOGNISED_NOTIFICATION_URL,
        )

        validate_reference_registry()
        self._discriminators = DISCRIMINATOR_REFERENCES
        self._omitted_targets = OMITTED_TARGET_RELATIONS
        self._payment_targets = PAYMENT_SUBJECT_REFERENCES
        self._orphan_kind = ORPHANED_PAYMENT_SUBJECT_KIND
        self._unknown_url = UNRECOGNISED_NOTIFICATION_URL
        self._url_routes = tuple(
            (re.compile(route.pattern), route.target_model_label)
            for route in NOTIFICATION_URL_ROUTES
        )
        self.makerspace_id = makerspace_id
        self.path = Path(root, "migration", "reference_provenance.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")

    def close(self):
        self._handle.close()

    def prepare_rows(self, model_label, rows):
        plain_rows = [item[0] if isinstance(item, tuple) else item for item in rows]
        self._validate_discriminators(model_label, plain_rows)
        if model_label == "payments.Payment":
            present = self._present_payment_subjects(plain_rows)
        else:
            present = set()
        for row in plain_rows:
            self._record_row(row, present)

    def project(self, row, field_name, value):
        disposition = self._omitted_targets.get((row._meta.label, field_name))
        return None if disposition is not None else value

    def _validate_discriminators(self, model_label, rows):
        edge = (model_label, "target_type", "target_id")
        targets = self._discriminators.get(edge)
        if targets is None:
            return
        for row in rows:
            if row.target_type not in targets:
                raise ExportIntegrityError(
                    f"{model_label} row {row.pk} has undeclared "
                    f"target_type={row.target_type!r}."
                )

    def _present_payment_subjects(self, rows):
        grouped = defaultdict(set)
        for row in rows:
            target_label = self._payment_targets.get(row.subject_type)
            if target_label is None:
                raise ExportIntegrityError(
                    f"payments.Payment row {row.pk} has undeclared "
                    f"subject_type={row.subject_type!r}."
                )
            grouped[target_label].add(row.subject_id)
        present = set()
        for target_label, ids in grouped.items():
            dataset = next(
                item
                for item in DATASETS.values()
                if item.fidelity is Fidelity.PORTABLE and item.model == target_label
            )
            model = apps.get_model(target_label)
            found = model.objects.filter(
                dataset.predicate.as_q(self.makerspace_id), pk__in=ids
            ).values_list("pk", flat=True)
            present.update((target_label, value) for value in found)
        return present

    def _record_row(self, row, present_payment_subjects):
        label = row._meta.label
        for (source_label, field_name), disposition in self._omitted_targets.items():
            if source_label != label:
                continue
            value = getattr(row, row._meta.get_field(field_name).attname)
            if value is not None:
                self._write(
                    row,
                    field_name,
                    disposition.kind,
                    {
                        "source_target_id": str(value),
                        "target_model_label": disposition.target_model_label,
                    },
                )
        if label == "payments.Payment":
            target_label = self._payment_targets[row.subject_type]
            if (target_label, row.subject_id) not in present_payment_subjects:
                self._write(
                    row,
                    "subject_id",
                    self._orphan_kind,
                    {
                        "source_target_id": str(row.subject_id),
                        "subject_label": row.subject_label,
                        "subject_type": row.subject_type,
                        "target_model_label": target_label,
                    },
                )
        if label == "notifications.Notification" and row.url_path:
            if not any(pattern.fullmatch(row.url_path) for pattern, _label in self._url_routes):
                self._write(
                    row,
                    "url_path",
                    self._unknown_url.kind,
                    {"source_url_path": row.url_path},
                )

    def _write(self, row, field_name, kind, detail):
        record = {
            "source_model_label": row._meta.label,
            "source_object_id": str(row.pk),
            "field_name": field_name,
            "kind": kind,
            "detail": detail,
        }
        self._handle.write(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        )
