"""Observe availability edges while the availability service holds the product lock."""

from apps.integrations.destinations import NotificationScope
from apps.integrations.email_templates_registry_helpers import bag
from apps.integrations.notifications_research import bounded, notify_family, safe_adapter


def save_stock_change(product, *, update_fields):
    point = product.reorder_point
    if point <= 0 or product.is_archived or "available_quantity" not in update_fields:
        product.save(update_fields=update_fields)
        return
    # Read the committed-before value under the caller's existing row lock. Comparing
    # against the database also handles stale instances and repeated writes in one txn.
    previous = type(product).objects.values_list("available_quantity", flat=True).get(pk=product.pk)
    product.save(update_fields=update_fields)
    if previous > point >= product.available_quantity:
        notify_low_stock(product)


@safe_adapter
def notify_low_stock(product):
    # notify_family queues after commit and honors the F3 matrix, mutes and quotas.
    # All labels/counts are snapshotted here; a later replenishment cannot rewrite it.
    return notify_family(
        product.makerspace, "stock", "low_stock",
        bag(id=product.pk, name=bounded(product.name),
            available=product.available_quantity, reorder_point=product.reorder_point),
        data={"product_id": product.pk},
        scope=NotificationScope(category=product.category_id),
    )
