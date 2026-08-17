"""Closed JSON schemas for cross-tenant reference snapshots."""

from datetime import datetime

from django.core.exceptions import ValidationError

STRING = "string"
INTEGER = "integer"
BOOLEAN = "boolean"
TIMESTAMP = "timestamp"


def object_schema(**fields):
    return {"type": "object", "fields": fields, "required": frozenset(fields)}


def array_schema(items):
    return {"type": "array", "items": items}


# Nothing here is nullable, and that follows from WHEN a snapshot is written rather
# than from the columns being non-nullable. Most of these columns are nullable, but
# `ExternalReferenceWriter.project` records provenance only for a reference that exists
# AND belongs to another makerspace -- a null column is left null and produces no
# snapshot at all, so a null can never reach validation. `Box.makerspace` is genuinely
# non-null. Declaring these nullable would only stop the schema catching a builder that
# silently produced nothing.
MAKERSPACE = object_schema(name=STRING, slug=STRING)
EVENT = object_schema(title=STRING, starts_at=TIMESTAMP, ends_at=TIMESTAMP)
CONTAINER = object_schema(label=STRING, makerspace=MAKERSPACE)
SOURCE_REFERENCE = object_schema(
    source_id=INTEGER,
    target_model_label=STRING,
    state=STRING,
    label=STRING,
)
SOURCE_REFERENCES = object_schema(references=array_schema(SOURCE_REFERENCE))
STOCK_TRANSFER = object_schema(
    source_id=INTEGER,
    reason=STRING,
    status=STRING,
    created_at=TIMESTAMP,
    owner=MAKERSPACE,
    source=MAKERSPACE,
    destination=MAKERSPACE,
)
STOCK_TRANSFER_LINE = object_schema(
    source_id=INTEGER,
    transfer_source_id=INTEGER,
    product_name=STRING,
    asset_label=STRING,
    quantity=INTEGER,
    from_status=STRING,
    to_status=STRING,
    notes=STRING,
)
WARRANTY_DOCUMENT = object_schema(
    source_id=INTEGER,
    warranty_source_id=INTEGER,
    original_filename=STRING,
    content_type=STRING,
    size_bytes=INTEGER,
)

EDGE_SCHEMAS = {
    ("events.EventCollaborator", "event"): EVENT,
    ("events.EventCollaborator", "makerspace"): MAKERSPACE,
    ("events.EventRegistration", "registered_via_makerspace"): MAKERSPACE,
    ("events.EventRegistration", "payment_via_makerspace"): MAKERSPACE,
    ("operations.StockTransfer", "source_container"): CONTAINER,
    ("operations.StockTransfer", "destination_container"): CONTAINER,
    ("operations.StockTransfer", "source_makerspace"): MAKERSPACE,
    ("operations.StockTransfer", "destination_makerspace"): MAKERSPACE,
    ("payments.Payment", "via_makerspace"): MAKERSPACE,
    ("hardware_requests.HardwareRequestItemAsset", "asset"): SOURCE_REFERENCE,
    ("hardware_requests.PublicToolLoan", "qr_code"): SOURCE_REFERENCE,
    ("hardware_requests.PublicToolLoan", "asset_ids"): SOURCE_REFERENCES,
    ("hardware_requests.PublicToolLoan", "qr_ids"): SOURCE_REFERENCES,
    (
        "hardware_requests.PublicToolLoan",
        "target_type+target_id",
    ): SOURCE_REFERENCE,
    ("boxes.QrCode", "target_type+target_id"): SOURCE_REFERENCE,
    ("boxes.QrScanEvent", "qr_code"): SOURCE_REFERENCE,
    ("operations.QrPrintBatchItem", "qr_code"): SOURCE_REFERENCE,
    ("operations.QrPrintBatchItem", "target_type+target_id"): SOURCE_REFERENCE,
    ("operations.StocktakeLine", "asset"): SOURCE_REFERENCE,
    ("operations.InventoryAdjustment", "asset"): SOURCE_REFERENCE,
    ("operations.StocktakeLedgerEntry", "asset"): SOURCE_REFERENCE,
    ("operations.StockTransferLine", "asset"): SOURCE_REFERENCE,
    ("warranty.Warranty", "asset"): SOURCE_REFERENCE,
    ("operations.StockTransfer", "inbound_transfer"): STOCK_TRANSFER,
    ("operations.StockTransferLine", "inbound_transfer"): STOCK_TRANSFER_LINE,
    ("operations.InventoryAdjustment", "transfer"): STOCK_TRANSFER,
    ("warranty.WarrantyDocument", "external_warranty"): WARRANTY_DOCUMENT,
}


def validate_snapshot(source_model_label, field_name, snapshot):
    """Reject snapshots that do not exactly match their declared edge schema."""
    edge = (source_model_label, field_name)
    schema = EDGE_SCHEMAS.get(edge)
    if schema is None:
        raise ValidationError({"snapshot": f"Unknown external reference edge: {edge!r}."})
    _validate_value(snapshot, schema, path="snapshot")


def _validate_value(value, schema, *, path):
    if isinstance(schema, dict):
        if schema["type"] == "array":
            if not isinstance(value, list):
                raise ValidationError({"snapshot": f"{path} must be an array."})
            for index, item in enumerate(value):
                _validate_value(item, schema["items"], path=f"{path}[{index}]")
            return
        if not isinstance(value, dict):
            raise ValidationError({"snapshot": f"{path} must be an object."})
        fields = schema["fields"]
        missing = schema["required"] - value.keys()
        if missing:
            raise ValidationError(
                {"snapshot": f"{path} is missing required keys: {', '.join(sorted(missing))}."}
            )
        extra = value.keys() - fields.keys()
        if extra:
            raise ValidationError(
                {"snapshot": f"{path} has unknown keys: {', '.join(sorted(extra))}."}
            )
        for key, field_schema in fields.items():
            _validate_value(value[key], field_schema, path=f"{path}.{key}")
        return

    valid = {
        STRING: lambda item: isinstance(item, str),
        INTEGER: lambda item: isinstance(item, int) and not isinstance(item, bool),
        BOOLEAN: lambda item: isinstance(item, bool),
        TIMESTAMP: _is_timestamp,
    }[schema](value)
    if not valid:
        raise ValidationError({"snapshot": f"{path} must be a {schema}."})


def _is_timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True
