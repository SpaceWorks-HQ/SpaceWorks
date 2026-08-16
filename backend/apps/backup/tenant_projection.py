"""Lossless tenant rows with explicit snapshots for cross-tenant edges."""

import json

from django.core import serializers


def project_dataset(label, queryset, makerspace_id):
    """Return Django fixture JSON plus non-restorable external references.

    Phase 5A tenant archives are downloadable evidence, not import bundles.  Even so,
    they must never imply that a relationship owned by another tenant can be restored
    as a live foreign key.  The small, locked set of shared edges is projected here;
    all other tenant-owned rows retain their complete database representation.
    """
    rows = list(queryset)
    references = []
    if label == "events.EventCollaborator":
        references.extend(_event_collaborator_references(rows, makerspace_id))
        rows = []
    elif label == "operations.StockTransfer":
        rows, references = _project_transfers(rows, makerspace_id)
    elif label == "operations.StockTransferLine":
        rows = [row for row in rows if row.transfer.makerspace_id == makerspace_id]

    payload = json.loads(serializers.serialize("json", rows))
    if label == "events.EventRegistration":
        references.extend(_null_external_makerspaces(
            payload, rows, makerspace_id,
            ("registered_via_makerspace", "payment_via_makerspace"),
        ))
    elif label == "payments.Payment":
        references.extend(_null_external_makerspaces(
            payload, rows, makerspace_id, ("via_makerspace",),
        ))
    elif label == "operations.StockTransfer":
        references.extend(_null_transfer_counterparty(payload, rows, makerspace_id))
    return json.dumps(payload, sort_keys=True), references, [row.pk for row in rows]


def _event_collaborator_references(rows, makerspace_id):
    result = []
    for row in rows:
        if row.event.makerspace_id == makerspace_id:
            result.append({
                "type": "hosted_event_collaborator",
                "event": _event_snapshot(row.event),
                "makerspace": _makerspace_snapshot(row.makerspace),
                "status": row.status,
                "recorded_at": row.responded_at or row.created_at,
            })
        else:
            result.append({
                "type": "foreign_host_event",
                "event": _event_snapshot(row.event),
                "host": _makerspace_snapshot(row.event.makerspace),
                "status": row.status,
                "recorded_at": row.responded_at or row.created_at,
            })
    return result


def _project_transfers(rows, makerspace_id):
    owned, references = [], []
    for row in rows:
        if row.source_makerspace_id and row.makerspace_id != row.source_makerspace_id:
            raise ValueError(
                f"StockTransfer {row.pk} owner disagrees with its source participant."
            )
        if row.makerspace_id == makerspace_id:
            owned.append(row)
            continue
        references.append({
            "type": "inbound_stock_transfer",
            "source": _makerspace_snapshot(row.source_makerspace),
            "destination": _makerspace_snapshot(row.destination_makerspace),
            "status": row.status,
            "recorded_at": row.applied_at or row.created_at,
        })
    return owned, references


def _null_external_makerspaces(payload, rows, makerspace_id, field_names):
    result = []
    for item, row in zip(payload, rows, strict=True):
        for field_name in field_names:
            related = getattr(row, field_name)
            if related is None or related.pk == makerspace_id:
                continue
            item["fields"][field_name] = None
            result.append({
                "type": f"{item['model']}.{field_name}",
                "row_pk": item["pk"],
                "makerspace": _makerspace_snapshot(related),
                "recorded_at": getattr(row, "created_at", None),
            })
    return result


def _null_transfer_counterparty(payload, rows, makerspace_id):
    result = []
    for item, row in zip(payload, rows, strict=True):
        for side in ("source", "destination"):
            related = getattr(row, f"{side}_makerspace")
            if related is None or related.pk == makerspace_id:
                continue
            item["fields"][f"{side}_makerspace"] = None
            item["fields"][f"{side}_container"] = None
            result.append({
                "type": f"operations.StockTransfer.{side}",
                "row_pk": item["pk"],
                "makerspace": _makerspace_snapshot(related),
                "recorded_at": row.applied_at or row.created_at,
            })
    return result


def _makerspace_snapshot(makerspace):
    if makerspace is None:
        return None
    return {"name": makerspace.name, "slug": makerspace.slug}


def _event_snapshot(event):
    return {
        "title": event.title,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
    }
