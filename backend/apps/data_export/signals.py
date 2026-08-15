import logging

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.data_export.models import DataExportJob

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=DataExportJob)
def release_export_archive(sender, instance, **kwargs):
    """Delete and uncharge an archive after any committed row-deletion path."""
    if not instance.object_key:
        return

    def release():
        from apps.data_export import storage
        from apps.makerspaces import limits

        try:
            if storage.delete_object(instance.object_key):
                limits.free_storage(instance.makerspace, instance.accounted_size_bytes)
        except Exception:
            logger.exception(
                "data_export_archive_release_failed",
                extra={"job_id": str(instance.pk), "makerspace_id": instance.makerspace_id},
            )

    transaction.on_commit(release)
