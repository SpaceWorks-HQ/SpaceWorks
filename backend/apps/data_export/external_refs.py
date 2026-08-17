"""Portable snapshots for references that cannot remain live foreign keys."""

import json
from pathlib import Path

from apps.separability.registry import runtime_active

from .errors import ExportIntegrityError
from .fields import EXTERNAL_REFERENCES
from .closure_refs import ClosureReferenceProjector, select_related_paths as closure_paths

# The referenced row's owning makerspace, per edge. A makerspace-valued edge owns
# itself; every other edge is owned by the makerspace its target row belongs to.
_CONTAINER_EDGES = frozenset({
    ("operations.StockTransfer", "source_container"),
    ("operations.StockTransfer", "destination_container"),
})
_EVENT_EDGES = frozenset({("events.EventCollaborator", "event")})


def select_related_paths(model_label):
    from apps.tenant_migration.closure_references import MOVABLE_ROW_REFERENCES

    paths = set()
    for label, field_name in EXTERNAL_REFERENCES:
        if label != model_label:
            continue
        paths.add(field_name)
        if (label, field_name) in _CONTAINER_EDGES:
            paths.add(f"{field_name}__makerspace")
    if model_label == "events.EventCollaborator":
        # The hosted-collaboration anchor is the local Event, so it is needed even
        # when the projected field is the collaborator's own foreign makerspace.
        paths.add("event")
    paths.update(closure_paths(model_label, MOVABLE_ROW_REFERENCES))
    return paths


class ExternalReferenceWriter:
    """Append validated typed provenance in dataset/keyset order."""

    def __init__(self, root, makerspace_id):
        if not runtime_active("tenant_migration"):
            raise ExportIntegrityError(
                "PORTABLE export requires the tenant_migration module."
            )
        # Keep this import behind the runtime guard: REDACTED exports must still
        # work in deployments where tenant_migration has been tombstoned.
        from apps.tenant_migration.schemas import validate_snapshot

        self._validate_snapshot = validate_snapshot
        self._closure = ClosureReferenceProjector(makerspace_id, self._write_record)
        self.makerspace_id = makerspace_id
        self.path = Path(root, "migration", "external_references.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")

    def close(self):
        self._handle.close()

    def prepare_rows(self, model_label, rows):
        self._closure.prepare_rows(model_label, rows)

    def project_closure(self, row, field_name, value):
        return self._closure.project(row, field_name, value)

    def project(self, row, field_name, value):
        """Return the cell value, recording provenance only for a FOREIGN reference.

        These columns are foreign only *sometimes*, and the common case is local:
        `registered_via_makerspace` is stamped `via_makerspace or locked.makerspace`,
        so an ordinary registration names the host tenant itself, and an outbound
        `StockTransfer.source_makerspace` is the migrating tenant. Snapshotting those
        would null a live local reference the importer can perfectly well remap, and
        write one junk provenance row per registration.
        """
        edge = (row._meta.label, field_name)
        if edge not in EXTERNAL_REFERENCES:
            raise ExportIntegrityError(f"Unknown external reference edge: {edge!r}.")
        if value in (None, ""):
            return value
        related = getattr(row, field_name)
        if related is None:
            raise ExportIntegrityError(
                f"{edge[0]} row {row.pk} has {field_name}={value!r} but no such row."
            )
        if _owner_makerspace_id(edge, related) == self.makerspace_id:
            return value
        snapshot = _snapshot(edge, related)
        try:
            self._validate_snapshot(edge[0], field_name, snapshot)
        except Exception as exc:
            raise ExportIntegrityError(
                f"{edge[0]} row {row.pk} has an invalid {field_name} snapshot."
            ) from exc
        target_label, target_id = _anchor(row, edge)
        self._write_record(
            row,
            field_name,
            snapshot,
            anchor=(target_label, target_id),
        )
        return None

    def _write_record(self, row, field_name, snapshot, *, anchor):
        try:
            self._validate_snapshot(row._meta.label, field_name, snapshot)
        except Exception as exc:
            raise ExportIntegrityError(
                f"{row._meta.label} row {row.pk} has an invalid {field_name} snapshot."
            ) from exc
        if isinstance(anchor, tuple):
            target_label, target_id = anchor
        elif anchor is None:
            target_label, target_id = row._meta.label, str(row.pk)
        else:
            target_label, target_id = anchor._meta.label, str(anchor.pk)
        record = {
            "source_model_label": row._meta.label,
            "source_object_id": str(row.pk),
            "field_name": field_name,
            "target_model_label": target_label,
            "target_object_id": target_id,
            "snapshot": snapshot,
        }
        self._handle.write(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        )


def _owner_makerspace_id(edge, related):
    if edge in _CONTAINER_EDGES or edge in _EVENT_EDGES:
        return related.makerspace_id
    return related.pk


def _snapshot(edge, related):
    if edge in _EVENT_EDGES:
        return {
            "title": related.title,
            "starts_at": related.starts_at.isoformat(),
            "ends_at": related.ends_at.isoformat(),
        }
    if edge in _CONTAINER_EDGES:
        return {
            "label": related.label,
            "makerspace": _makerspace_snapshot(related.makerspace),
        }
    return _makerspace_snapshot(related)


def _makerspace_snapshot(makerspace):
    return {"name": makerspace.name, "slug": makerspace.slug}


def _anchor(row, edge):
    """The LOCAL row this provenance hangs off, so a purge can find it later."""
    if edge == ("events.EventCollaborator", "makerspace"):
        # A hosted event's collaborator row is itself foreign-owned; the tenant row
        # it belongs to is the Event. Several foreign collaborators of one event all
        # anchor here, which is why the anchor index is not unique.
        return row.event._meta.label, str(row.event_id)
    return row._meta.label, str(row.pk)
