"""Notify only at the existing restock-created and received-status edges."""

from apps.integrations.destinations import NotificationScope
from apps.integrations.email_templates_registry_helpers import bag
from apps.integrations.notifications_research import bounded, notify_family, safe_adapter


@safe_adapter
def notify_stock(item, event):
    # Preserve a known machine as well as its type: a room narrowed to this one
    # machine should receive its restock alert, not just type-wide rooms.
    machine_id = item.resulting_machine_id
    if machine_id is None and item.source_pool_id:
        machine_id = item.source_pool.machine_id
    if machine_id is None and item.resulting_pool_id:
        machine_id = item.resulting_pool.machine_id
    return notify_family(
        item.makerspace, "stock", event, bag(id=item.pk, name=bounded(item.name)),
        data={"to_buy_item_id": item.pk, "pool_id": item.source_pool_id},
        scope=NotificationScope(machine=machine_id, machine_type=item.machine_type_id),
    )
