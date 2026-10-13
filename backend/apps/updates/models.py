from django.db import models


class PlatformUpdateSettings(models.Model):
    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        FAILED = "failed", "Failed"

    automatic_updates_enabled = models.BooleanField(default=False)
    release_notes = models.TextField(blank=True)
    release_url = models.URLField(blank=True)
    running_since = models.DateTimeField(null=True, blank=True)
    pre_update_version = models.CharField(max_length=80, blank=True)
    pre_update_archive = models.ForeignKey(
        "backup.BackupArchive", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="platform_update_snapshots",
    )
    rollback_restore = models.ForeignKey(
        "backup.RestoreOperation", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="platform_update_rollbacks",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.IDLE,
    )
    current_version = models.CharField(max_length=80, blank=True)
    available_version = models.CharField(max_length=80, blank=True)
    target_version = models.CharField(max_length=80, blank=True)
    update_requested_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_updated_at = models.DateTimeField(null=True, blank=True)
    last_backup_at = models.DateTimeField(null=True, blank=True)
    last_backup_name = models.CharField(max_length=120, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Platform update settings"
