from django.db.models.signals import post_delete
from django.dispatch import receiver

from .archive_retention import schedule_import_archive_unlink
from .models_import_job import TenantImportJob


@receiver(post_delete, sender=TenantImportJob)
def unlink_deleted_import_archive(sender, instance, **kwargs):
    """Remove the staged archive after every committed job-deletion path."""
    schedule_import_archive_unlink(instance.archive_path, instance.pk)
