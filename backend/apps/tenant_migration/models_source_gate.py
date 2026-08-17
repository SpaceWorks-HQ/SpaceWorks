import uuid

from django.conf import settings
from django.db import models


class SourceMigrationGate(models.Model):
    """Durable ownership and lease for one source tenant's migration freeze."""

    class State(models.TextChoices):
        OPEN = "open", "Open"
        DRAINING = "draining", "Draining uploads"
        QUIESCED = "quiesced", "Quiesced"
        MIGRATED_OUT = "migrated_out", "Migrated out"

    makerspace = models.OneToOneField(
        "makerspaces.Makerspace",
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="source_migration_gate",
    )
    state = models.CharField(
        max_length=16, choices=State.choices, default=State.OPEN
    )
    owner_id = models.UUIDField(null=True, blank=True)
    fencing_token = models.PositiveBigIntegerField(default=0)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="owned_source_migration_gates",
    )
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    presign_drain_until = models.DateTimeField(null=True, blank=True)
    quiesced_at = models.DateTimeField(null=True, blank=True)
    reopened_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(state="open", owner_id__isnull=True)
                    | models.Q(
                        state__in=("draining", "quiesced", "migrated_out"),
                        owner_id__isnull=False,
                        heartbeat_at__isnull=False,
                        lease_expires_at__isnull=False,
                    )
                ),
                name="ck_source_gate_owner_state",
            )
        ]

    @staticmethod
    def new_owner_id():
        return uuid.uuid4()
