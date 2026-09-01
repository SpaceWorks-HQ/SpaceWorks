"""Lossless tenant projection from raw records, including boundary snapshots."""

from collections.abc import Mapping
import json

from apps.backup.raw_projection import RawProjectionViolation, fixture_payload


def project_raw_dataset(label, model, records, makerspace_id):
    """Return fixture JSON and non-restorable references from raw mappings only."""
    rows = list(records)
    if any(not isinstance(row, Mapping) for row in rows):
        raise RawProjectionViolation(
            "project_raw_dataset() accepts values()/values_list()-style raw records only."
        )
    references = []
    if label == "events.EventCollaborator":
        references.extend(_event_collaborator_references(rows, makerspace_id))
        for item, row in zip(references, rows, strict=True):
            item["row_preimage"] = fixture_payload(model, (row,))[0]
        rows = []
    elif label == "operations.StockTransfer":
        rows, references = _project_transfers(rows, makerspace_id)
    elif label == "operations.StockTransferLine":
        rows = [row for row in rows if row["_transfer_makerspace_id"] == makerspace_id]

    payload = fixture_payload(model, rows)
    if label == "events.EventRegistration":
        references.extend(_null_external_makerspaces(
            payload,
            rows,
            makerspace_id,
            ("registered_via_makerspace", "payment_via_makerspace"),
        ))
    elif label == "payments.Payment":
        references.extend(_null_external_makerspaces(
            payload, rows, makerspace_id, ("via_makerspace",)
        ))
    elif label == "operations.StockTransfer":
        references.extend(_null_transfer_counterparty(payload, rows, makerspace_id))
    return json.dumps(payload, sort_keys=True), references, [
        row[model._meta.pk.attname] for row in rows
    ]


def project_dataset(*args, **kwargs):
    """Reject the retired model-materializing producer."""
    raise RawProjectionViolation(
        "project_dataset() is retired; project_raw_dataset() requires raw records."
    )


def _event_collaborator_references(rows, makerspace_id):
    result = []
    for row in rows:
        common = {
            "event": _event_snapshot(row),
            "status": row["status"],
            "recorded_at": row["responded_at"] or row["created_at"],
        }
        if row["_event_makerspace_id"] == makerspace_id:
            result.append({
                "type": "hosted_event_collaborator",
                **common,
                "makerspace": _makerspace_snapshot(row, "_makerspace"),
            })
        else:
            result.append({
                "type": "foreign_host_event",
                **common,
                "host": _makerspace_snapshot(row, "_event_makerspace"),
            })
    return result


def _project_transfers(rows, makerspace_id):
    owned, references = [], []
    for row in rows:
        if row["source_makerspace_id"] and row["makerspace_id"] != row["source_makerspace_id"]:
            raise ValueError(
                f"StockTransfer {row['id']} owner disagrees with its source participant."
            )
        if row["makerspace_id"] == makerspace_id:
            owned.append(row)
            continue
        references.append({
            "type": "inbound_stock_transfer",
            "source": _makerspace_snapshot(row, "_source_makerspace"),
            "destination": _makerspace_snapshot(row, "_destination_makerspace"),
            "status": row["status"],
            "recorded_at": row["applied_at"] or row["created_at"],
        })
    return owned, references


def _null_external_makerspaces(payload, rows, makerspace_id, field_names):
    result = []
    for item, row in zip(payload, rows, strict=True):
        for field_name in field_names:
            related_id = row[f"{field_name}_id"]
            if related_id is None or related_id == makerspace_id:
                continue
            item["fields"][field_name] = None
            result.append({
                "type": f"{item['model']}.{field_name}",
                "row_pk": item["pk"],
                "field_preimage": related_id,
                "makerspace": _makerspace_snapshot(row, f"_{field_name}"),
                "recorded_at": row.get("created_at"),
            })
    return result


def _null_transfer_counterparty(payload, rows, makerspace_id):
    result = []
    for item, row in zip(payload, rows, strict=True):
        for side in ("source", "destination"):
            field_name = f"{side}_makerspace"
            related_id = row[f"{field_name}_id"]
            if related_id is None or related_id == makerspace_id:
                continue
            item["fields"][field_name] = None
            item["fields"][f"{side}_container"] = None
            result.append({
                "type": f"operations.StockTransfer.{side}",
                "row_pk": item["pk"],
                "field_preimage": related_id,
                "makerspace": _makerspace_snapshot(row, f"_{field_name}"),
                "recorded_at": row["applied_at"] or row["created_at"],
            })
    return result


def _makerspace_snapshot(row, prefix):
    name = row[f"{prefix}_name"]
    slug = row[f"{prefix}_slug"]
    return None if name is None and slug is None else {"name": name, "slug": slug}


def _event_snapshot(row):
    return {
        "title": row["_event_title"],
        "starts_at": row["_event_starts_at"],
        "ends_at": row["_event_ends_at"],
    }
