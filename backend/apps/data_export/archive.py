"""Registry-driven CSV projection and archive assembly helpers."""

import copy
import csv
import json
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .errors import ExportIntegrityError
from .fields import EXTERNAL_REFERENCES
from .pii_raw import mapped_field_names
from .types import Fidelity, Redacted, Transformed

FREE_TEXT_TYPES = frozenset({"short_text", "paragraph"})
THEME_KEYS = frozenset({"mode", "primary_color", "accent_color", "logo_url"})


def write_dataset(
    path, dataset, rows, *, dangling_refs=None, pii_collector=None,
    external_writer=None, reference_writer=None, withheld_user_edges=None,
):
    if pii_collector is not None:
        pii_collector.register_model(dataset.model)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[column.name for column in dataset.columns])
        writer.writeheader()
        for item in rows:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], set):
                row, row_dangling = item
            else:
                row, row_dangling = item, dangling_refs or set()
            writer.writerow(
                project_row(
                    dataset, row, row_dangling,
                    pii_collector=pii_collector,
                    external_writer=external_writer,
                    reference_writer=reference_writer,
                    withheld_user_edges=withheld_user_edges or set(),
                )
            )


def project_row(
    dataset, row, dangling_refs, *, pii_collector=None, external_writer=None,
    reference_writer=None, withheld_user_edges=None,
):
    projected = {}
    portable_mapped = (
        frozenset(mapped_field_names(dataset.model))
        if dataset.fidelity is Fidelity.PORTABLE else frozenset()
    )
    for column in dataset.columns:
        source = column.sources[0]
        withheld = (dataset.model, row.pk, source) in (withheld_user_edges or set())
        if source in portable_mapped:
            if pii_collector is None:
                raise ExportIntegrityError(
                    f"PORTABLE projection of {dataset.model}.{source} requires "
                    "the raw PII collector."
                )
            value = pii_collector.project(row, source)
        else:
            value = source_value(row, source)
        if withheld:
            if external_writer is None:
                raise ExportIntegrityError("Withheld identity provenance requires a writer.")
            external_writer.withhold_identity(row, source)
            value = None
        elif (row.pk, source) in dangling_refs:
            value = None
        if external_writer is not None:
            value = external_writer.project_closure(row, source, value)
        if reference_writer is not None:
            value = reference_writer.project(row, source, value)
        projected[column.name] = csv_value(
            transform_value(
                dataset.model, source, column.disposition, value,
                row=row, external_writer=external_writer,
            )
        )
    return projected


def source_value(row, source):
    current = row
    parts = source.split("__")
    for index, part in enumerate(parts):
        if current is None:
            return None
        field = current._meta.get_field(part)
        terminal = index == len(parts) - 1
        if terminal and field.is_relation:
            return getattr(current, field.attname)
        current = getattr(current, part)
    return current


def transform_value(
    model, source, disposition, value, *, row=None, external_writer=None,
):
    if isinstance(disposition, Redacted):
        if (model, source) == ("audit.AuditLog", "meta"):
            return {"meta_redacted": True}
        if source == "custom_answers":
            return redact_custom_answers(value)
        return f"[{disposition.marker.upper()}]"
    if not isinstance(disposition, Transformed):
        return value
    if (model, source) in EXTERNAL_REFERENCES:
        if external_writer is None:
            raise ExportIntegrityError(
                f"PORTABLE projection of {model}.{source} requires the "
                "external-reference writer."
            )
        return external_writer.project(row, source, value)
    if source in {"map_url", "link"}:
        return strip_sensitive_url_parts(value)
    if (model, source) == ("makerspaces.Makerspace", "theme_config"):
        return {key: value[key] for key in THEME_KEYS if isinstance(value, dict) and key in value}
    return value


def redact_custom_answers(value):
    if not isinstance(value, dict) or not isinstance(value.get("answers"), list):
        return None if value is None else {"custom_answers_redacted": True}
    result = copy.deepcopy(value)
    for answer in result["answers"]:
        if not isinstance(answer, dict):
            continue
        if answer.get("type") in FREE_TEXT_TYPES:
            answer["value"] = "[REDACTED_FREE_TEXT]"
        elif answer.get("type") not in {
            "number", "date", "single_choice", "multi_choice", "dropdown", "yes_no"
        }:
            answer["value"] = "[REDACTED_UNKNOWN_TYPE]"
    return result


def strip_sensitive_url_parts(value):
    if not value:
        return value
    parts = urlsplit(str(value))
    hostname = parts.hostname or ""
    if not parts.scheme or not hostname:
        return ""
    netloc = hostname
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def write_manifest(root, manifest):
    Path(root, "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_readme(root):
    Path(root, "README.txt").write_text(
        """SpaceWorks makerspace data export

This archive is a human-readable snapshot of data owned by one makerspace. Each
dataset is a CSV file. It omits integration credentials, bearer tokens, platform
configuration, five operator-authored JSON configuration fields, and transient
authentication state. Audit metadata is replaced by a redaction marker, and free-text
custom-form answers are redacted according to the type stored with each answer.

The global users file is not a platform roster. It contains only users referenced by
the exported makerspace rows. For those referenced users, id + username is a new
intentional disclosure: the staff audit API returns only a numeric actor id and the
frontend omits the actor entirely. Usernames are identifying data and may correlate a
person across exports. No passwords, authority, verified identities, groups, or
permissions are included.

This REDACTED archive is for inspection and record-keeping. It is not the PORTABLE
migration archive and is not designed to recreate a makerspace on another deployment.
""",
        encoding="utf-8",
    )
