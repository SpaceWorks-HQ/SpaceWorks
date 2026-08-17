import logging

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.warranty.models import WarrantyDocument

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=WarrantyDocument)
def delete_warranty_document_object(sender, instance, **kwargs):
    """Best-effort remove the private bill from object storage on ANY delete path.

    `WarrantyDocumentDeleteView` already deletes the object, but a WarrantyDocument
    can also be removed by a CASCADE when its asset/printer/warranty/makerspace is
    deleted (printer-delete API, Django admin, makerspace purge). Without this the
    private file would orphan in object storage with no DB row left to collect.
    """
    # Local import keeps the storage (boto3/settings) dependency out of app loading.
    from apps.warranty import storage

    if not instance.object_key:
        return
    makerspace_id = instance.warranty.makerspace_id

    def delete_after_commit(key):
        from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
        from apps.tenant_migration.gate_runtime import tenant_write

        try:
            with tenant_write(makerspace_id):
                storage.delete_object(key)
        except SourceMigrationGateClosed:
            logger.info(
                "warranty_object_delete_skipped_closed_source_gate",
                extra={"makerspace_id": makerspace_id},
            )
        except Exception:  # pragma: no cover - delete_object is already best-effort
            logger.exception("Failed to delete warranty document object %s.", key)

    transaction.on_commit(lambda key=instance.object_key: delete_after_commit(key))
