import uuid

from django.conf import settings
from django.db import models
from django.db.models.lookups import Exact
from django.utils import timezone


def _octet_length_is_32(field_name):
    return Exact(
        models.Func(
            models.F(field_name),
            function="OCTET_LENGTH",
            output_field=models.IntegerField(),
        ),
        32,
    )


class AuditLog(models.Model):
    """Append-only audit event; database triggers are the real mutation guard."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=200, blank=True)
    target_id = models.CharField(max_length=100, blank=True)
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    meta = models.JSONField(default=dict)
    event_uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        null=True,
        blank=True,
        unique=True,
    )
    row_mac = models.BinaryField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["makerspace", "created_at"]),
            models.Index(fields=["action"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=_octet_length_is_32("row_mac"),
                name="ck_audit_log_row_mac_32_bytes",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("AuditLog rows are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("AuditLog rows are append-only.")

    def __str__(self):
        return f"{self.action} @ {self.created_at:%Y-%m-%d %H:%M:%S}"


class AuditMacKey(models.Model):
    """One wrapped row-MAC key for a makerspace or the global NULL scope."""

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="audit_mac_keys",
    )
    wrapped_key = models.BinaryField()
    # The AuditLog id from which this scope is attested. Rows at or below it predate
    # attestation and are legitimately unMACed; a row ABOVE it with no MAC means the MAC
    # was removed (or a fail-open incident occurred), which must never read as clean
    # history. Without this, one `UPDATE ... SET row_mac = NULL` defeats the whole feature.
    attested_from_id = models.BigIntegerField(default=0)
    # HMAC over (domain, scope, attested_from_id) under this scope's key. The cutover is
    # what makes a missing MAC detectable, so leaving it a bare mutable integer let an
    # SQL attacker strip a MAC and simply advance the cutover past it. Forging this
    # requires the master key, not just database access.
    attested_from_mac = models.BinaryField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace"],
                nulls_distinct=False,
                name="uniq_audit_mac_key_scope",
            ),
        ]

    def __str__(self):
        return f"Audit MAC key for makerspace {self.makerspace_id or 'global'}"


from .models_signing import (  # noqa: E402
    AuditBatch,
    AuditBatchLeaf,
    AuditSigningKey,
    AuditSigningKeyRotation,
    AuditSigningKeyRotationEvent,
)


__all__ = [
    "AuditBatch",
    "AuditBatchLeaf",
    "AuditLog",
    "AuditMacKey",
    "AuditSigningKey",
    "AuditSigningKeyRotation",
    "AuditSigningKeyRotationEvent",
]
