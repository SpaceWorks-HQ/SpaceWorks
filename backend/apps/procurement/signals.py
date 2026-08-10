import logging

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.procurement.models import ToBuyReceipt

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=ToBuyReceipt)
def delete_to_buy_receipt_object(sender, instance, **kwargs):
    """Best-effort remove the private receipt object on every delete path."""
    from apps.procurement import storage

    if not instance.object_key:
        return

    def delete_after_commit(key):
        try:
            storage.delete_object(key)
        except Exception:  # pragma: no cover - delete_object is already best-effort
            logger.exception("Failed to delete procurement receipt object %s.", key)

    transaction.on_commit(lambda key=instance.object_key: delete_after_commit(key))
