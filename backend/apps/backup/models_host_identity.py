"""Deployment-local database identity omitted from every archive artifact."""

import uuid

from django.db import models


class DeploymentDatabaseIdentity(models.Model):
    database_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    run_id = models.UUIDField(null=True, blank=True)
    artifact_sha256 = models.CharField(max_length=64, blank=True)
    capture_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(pk=1),
                name="backup_database_identity_singleton_pk",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        run_id__isnull=True,
                        artifact_sha256="",
                        capture_id__isnull=True,
                    )
                    | models.Q(
                        run_id__isnull=False,
                        artifact_sha256__regex=r"^[0-9a-f]{64}$",
                        capture_id__isnull=False,
                    )
                ),
                name="backup_database_identity_lineage_complete",
            )
        ]

    @classmethod
    def load(cls):
        row, _ = cls.objects.get_or_create(pk=1)
        return row

    def delete(self, *args, **kwargs):
        raise RuntimeError("The deployment database identity cannot be deleted.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("The deployment database identity cannot be changed.")
        return super().save(*args, **kwargs)
