from django.db import IntegrityError, transaction
from django.utils.text import slugify

from apps.admin_api.bulk_import_preview import preview_import
from apps.admin_api.bulk_import_rows import QUANTITY_BUCKET_FIELDS
from apps.audit import services as audit
from apps.boxes.models import Box
from apps.inventory.models import Category, InventoryProduct
from apps.makerspaces import limits


def apply_import(actor, makerspace, rows, mapping, progress_callback=None, allow_partial=False):
    preview = preview_import(makerspace, rows, mapping, progress_callback)
    if not preview["valid"] and not allow_partial:
        return {**preview, "applied": False}
    created = 0
    updated = 0
    with transaction.atomic():
        import_names = {
            item["data"]["name"]
            for item in preview["rows"]
            if item["action"] != "error"
        }
        existing_names = set(
            InventoryProduct.objects.filter(
                makerspace=makerspace,
                name__in=import_names,
            ).values_list("name", flat=True)
        )
        limits.check_quota(
            makerspace,
            "products",
            adding=len(import_names - existing_names),
        )
        for item in preview["rows"]:
            if item["action"] == "error":
                continue
            try:
                with transaction.atomic():
                    was_created = _apply_import_row(actor, makerspace, item)
            except IntegrityError as exc:
                _record_row_integrity_error(preview, item, exc)
                continue
            if was_created:
                created += 1
            else:
                updated += 1
        audit.record(
            actor,
            "inventory.bulk_imported",
            makerspace=makerspace,
            target=makerspace,
            meta={"created": created, "updated": updated},
        )
    _refresh_summary(preview)
    return {
        **preview,
        "applied": True,
        "partial": bool(preview["errors"]),
        "created": created,
        "updated": updated,
    }


def _apply_import_row(actor, makerspace, item):
    data = dict(item["data"])
    box_id = data.pop("box_id", None)
    box = Box.objects.filter(makerspace=makerspace, pk=box_id).first() if box_id else None
    name = data.pop("name")
    category_name = data.pop("category_name", "")
    if category_name:
        category, was_category_created = _category_for_name(makerspace, category_name)
        data["category_id"] = category.id
        if was_category_created:
            audit.record(
                actor,
                "category.created",
                makerspace=makerspace,
                target=category,
                meta={"source": "bulk_import"},
            )
    create_defaults = {**data, "box": box}
    product, was_created = InventoryProduct.objects.get_or_create(
        makerspace=makerspace, name=name, defaults=create_defaults
    )
    if was_created:
        return True
    update_defaults = {
        field: value for field, value in data.items() if field not in QUANTITY_BUCKET_FIELDS
    }
    update_defaults["box"] = box
    for field, value in update_defaults.items():
        setattr(product, field, value)
    product.save(update_fields=[*update_defaults.keys(), "updated_at"])
    return False


def _record_row_integrity_error(preview, item, exc):
    item["action"] = "error"
    message = _short_db_message(exc)
    preview["errors"].append({"row": item["row"], "errors": {"__all__": message}})
    preview["valid"] = False


def _short_db_message(exc):
    message = str(exc).strip()
    if not message:
        return "Database integrity error."
    return message.splitlines()[0][:240]


def _refresh_summary(preview):
    rows = preview["rows"]
    preview["summary"] = {
        **preview["summary"],
        "create": sum(1 for item in rows if item["action"] == "create"),
        "update": sum(1 for item in rows if item["action"] == "update"),
        "errors": len(preview["errors"]),
        "warnings": len(preview["warnings"]),
        "total": len(rows),
    }


def _category_for_name(makerspace, name):
    base_slug = slugify(name) or "category"
    slug = base_slug
    for _attempt in range(2):
        category = Category.objects.filter(makerspace=makerspace, name__iexact=name).first()
        if category:
            return category, False
        slug = base_slug
        suffix = 2
        while Category.objects.filter(makerspace=makerspace, slug=slug).exists():
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        try:
            with transaction.atomic():
                return Category.objects.create(makerspace=makerspace, name=name, slug=slug), True
        except IntegrityError:
            continue
    category = Category.objects.filter(makerspace=makerspace, name__iexact=name).first()
    if category:
        return category, False
    with transaction.atomic():
        return Category.objects.create(makerspace=makerspace, name=name, slug=slug), True
