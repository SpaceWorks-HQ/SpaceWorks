"""Bounded, snapshot-consistent execution of the F1 export registry."""

import logging
import shutil
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.utils import timezone

from . import REGISTRY_VERSION
from .archive import write_dataset, write_manifest, write_readme
from .datasets import DATASETS
from .errors import ExportIntegrityError
from .external_refs import ExternalReferenceWriter
from .pii_raw import PiiAadCollector
from .runner_queries import after_keyset, is_statement_timeout, key_value, select_declared_relations
from .reference_provenance import ReferenceProvenanceWriter
from .references import SEMANTIC_REFERENCES, USER_EDGES, require_raw_user
from .types import Fidelity, SemanticUserRef

logger = logging.getLogger(__name__)


class ExportDeadlineExceeded(RuntimeError):
    def __init__(self, dataset, rows_completed):
        self.dataset = dataset
        self.rows_completed = rows_completed
        super().__init__(
            f"Export deadline exceeded after {rows_completed} rows; last dataset: {dataset}."
        )


def build_archive(
    job, *, page_size=None, monotonic=time.monotonic, package=True,
    existing_snapshot=False,
):
    """Project an export; ``package=False`` returns its directory instead of a ZIP."""
    fidelity = Fidelity(job.fidelity)
    page_size = page_size or settings.DATA_EXPORT_PAGE_SIZE
    remaining = max(0.0, (job.deadline_at - timezone.now()).total_seconds())
    deadline_clock = monotonic() + remaining
    tempdir = tempfile.TemporaryDirectory(prefix="spaceworks-export-")
    root = Path(tempdir.name, "archive")
    root.mkdir()
    counts, closure = {}, set()
    snapshot_at = None
    current_path = "starting"
    total_rows = 0
    pii_collector = None
    external_writer = None
    reference_writer = None
    try:
        if existing_snapshot and not connection.in_atomic_block:
            raise ExportIntegrityError(
                "An existing export snapshot requires an active transaction."
            )
        if fidelity is Fidelity.PORTABLE:
            pii_collector = PiiAadCollector(job.makerspace_id)
            external_writer = ExternalReferenceWriter(root, job.makerspace_id)
            reference_writer = ReferenceProvenanceWriter(root, job.makerspace_id)
        with nullcontext() if existing_snapshot else transaction.atomic():
            with connection.cursor() as cursor:
                if not existing_snapshot:
                    cursor.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                timeout_ms = max(1, int(remaining * 1000))
                cursor.execute("SET LOCAL statement_timeout = %s", [timeout_ms])
                cursor.execute("SET LOCAL lock_timeout = %s", [timeout_ms])
                cursor.execute("SELECT transaction_timestamp()")
                snapshot_at = cursor.fetchone()[0]

            datasets = [
                dataset for dataset in DATASETS.values()
                if dataset.fidelity is fidelity and dataset.model != "accounts.User"
            ]
            for dataset in datasets:
                current_path = dataset.path
                rows, count = _read_dataset(
                    dataset, job.makerspace_id, closure, page_size, deadline_clock, monotonic
                )
                if fidelity is Fidelity.REDACTED:
                    write_dataset(root / dataset.path, dataset, rows)
                counts[dataset.path] = count
                total_rows += count

            users = DATASETS[(fidelity, "global/users.csv")]
            current_path = users.path
            user_rows, user_count = _read_users(
                users, closure, page_size, deadline_clock, monotonic
            )
            denied_ids = set()
            from .migration_admission import portable_approval

            approval = portable_approval(job) if fidelity is Fidelity.PORTABLE else None
            if fidelity is Fidelity.PORTABLE:
                from apps.tenant_migration.admission import withheld_edges
            if approval is not None:
                from apps.tenant_migration.admission import (
                    canonical_identities,
                    validate_snapshot_approval,
                )

                approved_ids = validate_snapshot_approval(
                    approval, canonical_identities(user_rows)
                )
                denied_ids = closure - approved_ids
                user_rows = [row for row in user_rows if row.pk in approved_ids]
                user_count = len(user_rows)
            if fidelity is Fidelity.PORTABLE:
                # Re-read one dataset at a time inside the same repeatable-read
                # snapshot. Approval must see the complete closure before any PII is
                # written, but retaining every tenant row in memory would be unbounded.
                for dataset in datasets:
                    current_path = dataset.path
                    rows, _count = _read_dataset(
                        dataset, job.makerspace_id, set(), page_size,
                        deadline_clock, monotonic,
                    )
                    withheld = withheld_edges([(dataset, rows)], denied_ids)
                    external_writer.prepare_rows(dataset.model, rows)
                    reference_writer.prepare_rows(dataset.model, rows)
                    write_dataset(
                        root / dataset.path, dataset, rows,
                        pii_collector=pii_collector,
                        external_writer=external_writer,
                        reference_writer=reference_writer,
                        withheld_user_edges=withheld,
                    )
            write_dataset(
                root / users.path, users, user_rows,
                pii_collector=pii_collector,
                external_writer=external_writer,
                reference_writer=reference_writer,
            )
            counts[users.path] = user_count
            total_rows += user_count
            _check_deadline(current_path, total_rows, deadline_clock, monotonic)
    except OperationalError as exc:
        if is_statement_timeout(exc):
            tempdir.cleanup()
            raise ExportDeadlineExceeded(current_path, total_rows) from exc
        raise
    except Exception:
        tempdir.cleanup()
        raise
    finally:
        if external_writer is not None:
            external_writer.close()
        if reference_writer is not None:
            reference_writer.close()

    if pii_collector is not None:
        pii_collector.write(root)

    manifest = {
        "fidelity": fidelity.value,
        "makerspace": {
            "id": job.makerspace_id,
            "slug": job.makerspace.slug,
            "name": job.makerspace.name,
        },
        "snapshot_at": snapshot_at.isoformat(),
        "row_counts": counts,
        "total_rows": total_rows,
        "deadline": {
            "seconds": settings.DATA_EXPORT_DEADLINE_SECONDS,
            "outcome": "completed",
        },
        "registry_version": REGISTRY_VERSION,
    }
    write_manifest(root, manifest)
    write_readme(root)
    if not package:
        return root, manifest, tempdir
    archive_base = Path(tempdir.name, "makerspace-export")
    zip_path = shutil.make_archive(str(archive_base), "zip", root)
    return zip_path, manifest, tempdir


def _read_dataset(dataset, tenant_id, closure, page_size, deadline, monotonic):
    model = apps.get_model(dataset.model)
    queryset = model.objects.filter(dataset.predicate.as_q(tenant_id))
    queryset = select_declared_relations(queryset, dataset)
    cursor_values, rows, count = None, [], 0
    while True:
        _check_deadline(dataset.path, count, deadline, monotonic)
        page_query = queryset
        if cursor_values is not None:
            page_query = page_query.filter(after_keyset(dataset.keyset, cursor_values))
        page = list(page_query.order_by(*dataset.keyset)[:page_size])
        if not page:
            break
        from .migration_admission import portable_projected_rows

        emitted, contributors = portable_projected_rows(dataset, page)
        dangling = _collect_user_ids(dataset, contributors, closure)
        _validate_dataset_integrity(dataset, page, tenant_id)
        rows.extend((row, dangling) for row in emitted)
        count += len(emitted)
        cursor_values = tuple(key_value(page[-1], name) for name in dataset.keyset)
        if any(value is None for value in cursor_values):
            raise ExportIntegrityError(
                f"{dataset.path} row {page[-1].pk} has an unexpected null keyset value."
            )
    return rows, count


def _read_users(dataset, closure, page_size, deadline, monotonic):
    model = apps.get_model("accounts.User")
    queryset = model.objects.filter(pk__in=closure)
    cursor_values, rows = None, []
    while True:
        _check_deadline(dataset.path, len(rows), deadline, monotonic)
        page_query = queryset
        if cursor_values is not None:
            page_query = page_query.filter(after_keyset(dataset.keyset, cursor_values))
        page = list(page_query.order_by(*dataset.keyset)[:page_size])
        if not page:
            break
        rows.extend(page)
        cursor_values = tuple(key_value(page[-1], name) for name in dataset.keyset)
        if any(value is None for value in cursor_values):
            raise ExportIntegrityError("global/users.csv contains a null keyset value.")
    return rows, len(rows)


def _collect_user_ids(dataset, rows, closure):
    user_model = apps.get_model("accounts.User")
    edges = [
        (field, edge) for (fidelity, label, field), edge in USER_EDGES.items()
        if fidelity is dataset.fidelity and label == dataset.model and edge.included
    ]
    candidates = set()
    row_values = []
    for row in rows:
        for field_name, edge in edges:
            field = row._meta.get_field(field_name)
            value = getattr(row, field_name if edge.raw else field.attname)
            if value is not None:
                candidates.add(int(value))
                row_values.append((row, field_name, edge, int(value)))
        _collect_semantic_user(dataset, row, candidates, row_values)
    existing = set(user_model.objects.filter(pk__in=candidates).values_list("pk", flat=True))
    dangling = set()
    for row, field_name, edge, value in row_values:
        if edge.raw:
            require_raw_user(
                dataset.fidelity, model=dataset.model, row_pk=row.pk,
                field=field_name, user_id=value, existing_user_ids=existing,
            )
        elif value not in existing:
            raise ExportIntegrityError(
                f"{dataset.model} row {row.pk} has dangling {field_name}={value}."
            )
        if value in existing:
            closure.add(value)
        else:
            dangling.add((row.pk, field_name))
    return dangling


def _collect_semantic_user(dataset, row, candidates, row_values):
    decisions = SEMANTIC_REFERENCES.get(
        (dataset.fidelity, dataset.model, "target_type+target_id"), ()
    )
    if any(isinstance(item, SemanticUserRef) and item.included for item in decisions):
        if str(getattr(row, "target_type", "")).lower() == "accounts.user":
            try:
                value = int(row.target_id)
            except (TypeError, ValueError) as exc:
                if dataset.fidelity is Fidelity.PORTABLE:
                    raise ExportIntegrityError(
                        f"{dataset.model} row {row.pk} has invalid target_id={row.target_id!r}."
                    ) from exc
                return
            candidates.add(value)
            row_values.append((row, "target_id", type("Edge", (), {"raw": True})(), value))


def _validate_dataset_integrity(dataset, rows, tenant_id):
    if dataset.model != "operations.StockTransfer":
        return
    for row in rows:
        if row.source_makerspace_id and row.makerspace_id != row.source_makerspace_id:
            raise ExportIntegrityError(
                f"operations.StockTransfer row {row.pk} owner {row.makerspace_id} "
                f"disagrees with source participant {row.source_makerspace_id}."
            )


def _check_deadline(path, count, deadline, monotonic):
    if monotonic() >= deadline:
        raise ExportDeadlineExceeded(path, count)
