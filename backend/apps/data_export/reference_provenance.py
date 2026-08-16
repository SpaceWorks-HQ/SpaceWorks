"""PORTABLE reference validation and typed inert-provenance output."""

import copy
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
            AUDIT_META_REFERENCES,
            AUDIT_TARGET_DISPOSITIONS,
            DISCRIMINATOR_REFERENCES,
            NOTIFICATION_URL_ROUTES,
            OMITTED_TARGET_RELATIONS,
            ORPHANED_PAYMENT_SUBJECT_KIND,
            PAYMENT_SUBJECT_REFERENCES,
            UNRECOGNISED_NOTIFICATION_URL,
            UNRECOGNISED_AUDIT_TARGET,
            normalize_audit_target_type,
        )
        from apps.tenant_migration.audit_references import (
            SOURCE_ID_PREFIX,
            AuditReferenceDisposition,
        )

        validate_reference_registry()
        self._discriminators = DISCRIMINATOR_REFERENCES
        self._audit_meta = AUDIT_META_REFERENCES
        self._audit_targets = AUDIT_TARGET_DISPOSITIONS
        self._unknown_audit_target = UNRECOGNISED_AUDIT_TARGET
        self._normalize_audit_target = normalize_audit_target_type
        self._source_id_prefix = SOURCE_ID_PREFIX
        self._audit_disposition = AuditReferenceDisposition
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
        if row._meta.label == "audit.AuditLog":
            return self._project_audit(row, field_name, value)
        disposition = self._omitted_targets.get((row._meta.label, field_name))
        return None if disposition is not None else value

    def _project_audit(self, row, field_name, value):
        target_disposition = self._audit_target_disposition(row.target_type)
        if field_name in {"target_type", "target_id"}:
            if (
                row.target_id
                and target_disposition.disposition
                is not self._audit_disposition.REMAP
            ):
                return ""
            return value
        if field_name == "meta":
            return self._project_audit_meta(row.action, value)
        return value

    def _project_audit_meta(self, action, value):
        if not isinstance(value, dict):
            return value
        return self._project_meta_dict(action, copy.deepcopy(value), "")

    def _project_meta_dict(self, action, value, prefix):
        projected = {}
        key_rule = self._audit_meta.get((action, f"{prefix}.<keys>")) if prefix else None
        for key, child in value.items():
            output_key = key
            if key_rule is not None:
                output_key = self._project_meta_id(key_rule, key)
            elif not isinstance(key, str) or key.isdigit():
                output_key = self._source_namespace(key)
            name = str(key)
            path = f"{prefix}.{name}" if prefix else name
            rule = self._audit_meta.get((action, path))
            if rule is not None:
                projected[output_key] = self._project_meta_id(rule, child)
            elif isinstance(child, dict):
                projected[output_key] = self._project_meta_dict(action, child, path)
            elif self._runtime_id_name(name):
                projected[output_key] = self._source_namespace_value(child)
            else:
                projected[output_key] = child
        return projected

    def _project_meta_id(self, rule, value):
        if rule.disposition is self._audit_disposition.REMAP:
            return value
        if rule.disposition is self._audit_disposition.NULL:
            return None
        return self._source_namespace_value(value)

    def _source_namespace_value(self, value):
        if value is None:
            return None
        if isinstance(value, list):
            return [self._source_namespace_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._source_namespace_value(item) for item in value]
        if isinstance(value, dict):
            return {
                self._source_namespace(key): self._source_namespace_value(child)
                for key, child in value.items()
            }
        return self._source_namespace(value)

    def _source_namespace(self, value):
        rendered = str(value)
        if rendered.startswith(self._source_id_prefix):
            return rendered
        return f"{self._source_id_prefix}{rendered}"

    @staticmethod
    def _runtime_id_name(name):
        return name == "id" or name.endswith(("_id", "_ids"))

    def _audit_target_disposition(self, target_type):
        normalized = self._normalize_audit_target(target_type)
        return self._audit_targets.get(normalized, self._unknown_audit_target)

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
        if label == "audit.AuditLog" and row.target_id:
            disposition = self._audit_target_disposition(row.target_type)
            if disposition.disposition is not self._audit_disposition.REMAP:
                self._write(
                    row,
                    "target_type+target_id",
                    disposition.kind,
                    {
                        "source_target_id": str(row.target_id),
                        "source_target_type": row.target_type,
                        "target_model_label": disposition.target_model_label,
                    },
                )
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
