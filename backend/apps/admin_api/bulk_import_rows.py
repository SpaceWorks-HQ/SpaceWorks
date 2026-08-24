from apps.boxes.models import Box
from apps.inventory.models import Category, InventoryProduct, PublicAvailabilityMode, TrackingMode


REQUIRED_FIELDS = {"name", "total_quantity", "available_quantity"}
OPTIONAL_FIELDS = {
    "description",
    "image_key",
    "tracking_mode",
    "is_public",
    "public_self_checkout_enabled",
    "show_public_count",
    "public_availability_mode",
    "storage_location",
    "category",
    "box_code",
    "reserved_quantity",
    "issued_quantity",
    "damaged_quantity",
    "lost_quantity",
}
VALID_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS
QUANTITY_BUCKET_FIELDS = {
    "total_quantity",
    "available_quantity",
    "reserved_quantity",
    "issued_quantity",
    "damaged_quantity",
    "lost_quantity",
}
DETAIL_WARNING_FIELDS = {"description", "storage_location", "category", "image_key"}


def _default_mapping(rows):
    if not rows:
        return {}
    lower = {str(key).strip().lower(): key for key in rows[0].keys()}
    return {field: lower[field] for field in VALID_FIELDS if field in lower}


def _normalize_row(makerspace, row, mapping):
    data = {}
    errors = {}
    warnings = {}
    for field in VALID_FIELDS:
        column = mapping.get(field)
        if column:
            data[field] = row.get(column)
    for field in REQUIRED_FIELDS:
        if data.get(field) in {None, ""}:
            errors[field] = "This field is required."
    for field in DETAIL_WARNING_FIELDS:
        column = mapping.get(field)
        if column and data.get(field) in {None, ""}:
            warnings[field] = "Optional detail is blank."

    for field in [
        "total_quantity",
        "available_quantity",
        "reserved_quantity",
        "issued_quantity",
        "damaged_quantity",
        "lost_quantity",
    ]:
        if field in data:
            data[field] = _int_value(data[field], field, errors)
    data.setdefault("reserved_quantity", 0)
    data.setdefault("issued_quantity", 0)
    data.setdefault("damaged_quantity", 0)
    data.setdefault("lost_quantity", 0)

    for field in ["is_public", "public_self_checkout_enabled", "show_public_count"]:
        if field in data:
            data[field] = _bool_value(data[field])
    data.setdefault("is_public", True)
    data.setdefault("public_self_checkout_enabled", False)
    data.setdefault("show_public_count", False)
    data.setdefault("tracking_mode", TrackingMode.QUANTITY)
    data.setdefault("public_availability_mode", PublicAvailabilityMode.STATUS_ONLY)
    if data["tracking_mode"] not in TrackingMode.values:
        errors["tracking_mode"] = "Invalid tracking mode."
    if data["public_availability_mode"] not in PublicAvailabilityMode.values:
        errors["public_availability_mode"] = "Invalid public availability mode."

    total_used = sum(
        data[field]
        for field in [
            "available_quantity",
            "reserved_quantity",
            "issued_quantity",
            "damaged_quantity",
            "lost_quantity",
        ]
    )
    if "total_quantity" in data and total_used > data["total_quantity"]:
        errors["total_quantity"] = "Quantity buckets cannot exceed total quantity."

    box_code = data.pop("box_code", None)
    data["box_id"] = None
    if box_code:
        box = Box.objects.filter(makerspace=makerspace, code=box_code).first()
        if box is None:
            errors["box_code"] = "Box code does not exist in this makerspace."
        else:
            data["box_id"] = box.id
    image_key = str(data.get("image_key") or "").strip()
    if image_key and not image_key.startswith(f"items/{makerspace.id}/"):
        errors["image_key"] = "Image key must belong to this makerspace."
    data["image_key"] = image_key

    category_name = str(data.pop("category", "") or "").strip()
    if category_name:
        category = Category.objects.filter(makerspace=makerspace, name__iexact=category_name).first()
        data["category_name"] = category_name
        data["category_id"] = category.id if category else None
    return data, errors, warnings


def _int_value(value, field, errors):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        errors[field] = "Must be an integer."
        return 0
    if parsed < 0:
        errors[field] = "Must be non-negative."
    return parsed


def _bool_value(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _existing_names(makerspace, rows, mapping):
    name_column = mapping.get("name")
    if not name_column:
        return set()
    names = [row.get(name_column) for row in rows if row.get(name_column)]
    return set(
        InventoryProduct.objects.filter(
            makerspace=makerspace,
            name__in=names,
        ).values_list("name", flat=True)
    )


def _row_action(normalized, existing_names):
    name = normalized.get("name")
    if not name:
        return "error"
    return "update" if name in existing_names else "create"
