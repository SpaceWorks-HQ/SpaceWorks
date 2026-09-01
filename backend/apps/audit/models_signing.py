"""Signing-key, rotation, and batch-attestation models."""

import uuid

from django.db import models
from django.db.models.lookups import Exact
from django.utils import timezone

from .models import AuditLog


def _octet_length_is_32(field_name):
    return Exact(
        models.Func(
            models.F(field_name),
            function="OCTET_LENGTH",
            output_field=models.IntegerField(),
        ),
        32,
    )


class AuditSigningKey(models.Model):
    """One generation of deployment-local Ed25519 authority for an audit scope."""

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="audit_signing_keys",
    )
    wrapped_private_key = models.BinaryField(null=True, blank=True)
    public_key = models.BinaryField()
    fingerprint = models.CharField(max_length=64)
    version = models.PositiveBigIntegerField(default=1)
    valid_from_seq = models.PositiveBigIntegerField(default=0)
    valid_to_seq = models.PositiveBigIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    activation_payload = models.JSONField(default=dict)
    activation_signature = models.BinaryField()
    created_at = models.DateTimeField(default=timezone.now)
    activated_at = models.DateTimeField(null=True, blank=True)
    # Row-local durable projection of a non-terminal rotation. PostgreSQL cannot make a
    # partial-index predicate depend on the latest immutable event in another table.
    pending_rotation = models.OneToOneField(
        "audit.AuditSigningKeyRotation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="pending_on_key",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace"],
                condition=models.Q(is_active=True),
                nulls_distinct=False,
                name="uniq_active_audit_signing_key_scope",
            ),
            models.UniqueConstraint(
                fields=["makerspace", "version"],
                nulls_distinct=False,
                name="uniq_audit_signing_key_scope_version",
            ),
            models.UniqueConstraint(
                fields=["makerspace"],
                condition=models.Q(pending_rotation__isnull=False),
                nulls_distinct=False,
                name="uniq_audit_pending_rotation_scope",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(valid_to_seq__isnull=True)
                    | models.Q(valid_to_seq__gte=models.F("valid_from_seq"))
                ),
                name="ck_audit_signing_key_valid_interval",
            ),
            models.CheckConstraint(
                condition=models.Q(pending_rotation__isnull=True)
                | models.Q(is_active=True),
                name="ck_audit_pending_rotation_on_active_key",
            ),
            models.CheckConstraint(
                condition=models.Q(is_active=False)
                | models.Q(
                    valid_to_seq__isnull=True,
                    wrapped_private_key__isnull=False,
                ),
                name="ck_active_audit_signing_key_open",
            ),
            models.CheckConstraint(
                condition=_octet_length_is_32("public_key"),
                name="ck_audit_signing_public_key_32_bytes",
            ),
            models.CheckConstraint(
                condition=Exact(
                    models.Func(
                        models.F("activation_signature"),
                        function="OCTET_LENGTH",
                        output_field=models.IntegerField(),
                    ),
                    64,
                ),
                name="ck_audit_activation_signature_64_bytes",
            ),
        ]

    def __str__(self):
        scope = self.makerspace_id or "global"
        return f"Audit signing key {scope}:v{self.version}"


class AuditSigningKeyRotation(models.Model):
    """Immutable dual-signed attempt between increasing key generations."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_signing_key_rotations",
    )
    old_key = models.ForeignKey(
        AuditSigningKey, on_delete=models.PROTECT, related_name="rotations_from"
    )
    new_key = models.OneToOneField(
        AuditSigningKey, on_delete=models.PROTECT, related_name="rotation_to"
    )
    old_fingerprint = models.CharField(max_length=64)
    new_fingerprint = models.CharField(max_length=64)
    old_version = models.PositiveBigIntegerField()
    new_version = models.PositiveBigIntegerField()
    last_old_batch_seq = models.PositiveBigIntegerField()
    last_old_batch_root = models.BinaryField()
    payload = models.JSONField()
    old_signature = models.BinaryField()
    new_signature = models.BinaryField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["makerspace_id", "old_version"]
        constraints = [
            models.CheckConstraint(
                condition=_octet_length_is_32("last_old_batch_root"),
                name="ck_audit_rotation_head_root_32_bytes",
            ),
            models.CheckConstraint(
                condition=Exact(
                    models.Func(models.F("old_signature"), function="OCTET_LENGTH", output_field=models.IntegerField()),
                    64,
                ),
                name="ck_audit_rotation_old_signature_64_bytes",
            ),
            models.CheckConstraint(
                condition=Exact(
                    models.Func(models.F("new_signature"), function="OCTET_LENGTH", output_field=models.IntegerField()),
                    64,
                ),
                name="ck_audit_rotation_new_signature_64_bytes",
            ),
            models.CheckConstraint(
                condition=models.Q(new_version__gt=models.F("old_version")),
                name="ck_audit_rotation_increasing_versions",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise RuntimeError("AuditSigningKeyRotation rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("AuditSigningKeyRotation rows are immutable.")


class AuditSigningKeyRotationEvent(models.Model):
    """Append-only state history for one signing-key rotation."""

    class State(models.TextChoices):
        PREPARED = "PREPARED", "Prepared"
        PUBLISHED = "PUBLISHED", "Published"
        FINALIZED = "FINALIZED", "Finalized"
        ABORTED = "ABORTED", "Aborted"

    rotation = models.ForeignKey(
        AuditSigningKeyRotation,
        on_delete=models.CASCADE,
        related_name="events",
    )
    state = models.CharField(max_length=16, choices=State.choices)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["rotation", "state"],
                name="uniq_audit_rotation_event_state",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("AuditSigningKeyRotationEvent rows are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("AuditSigningKeyRotationEvent rows are append-only.")


class AuditBatch(models.Model):
    """One signed set of audit rows, chained to the prior set in its scope."""

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_batches",
    )
    batch_seq = models.PositiveBigIntegerField()
    leaf_count = models.PositiveIntegerField()
    merkle_root = models.BinaryField()
    prev_batch_root = models.BinaryField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    signature = models.BinaryField()
    signer_fingerprint = models.CharField(max_length=64)

    class Meta:
        ordering = ["makerspace_id", "batch_seq"]
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "batch_seq"],
                nulls_distinct=False,
                name="uniq_audit_batch_scope_seq",
            ),
            models.CheckConstraint(
                condition=models.Q(leaf_count__gt=0),
                name="ck_audit_batch_leaf_count_positive",
            ),
            models.CheckConstraint(
                condition=_octet_length_is_32("merkle_root"),
                name="ck_audit_batch_merkle_root_32_bytes",
            ),
            models.CheckConstraint(
                condition=_octet_length_is_32("prev_batch_root"),
                name="ck_audit_batch_prev_root_32_bytes",
            ),
            models.CheckConstraint(
                condition=Exact(
                    models.Func(
                        models.F("signature"),
                        function="OCTET_LENGTH",
                        output_field=models.IntegerField(),
                    ),
                    64,
                ),
                name="ck_audit_batch_signature_64_bytes",
            ),
        ]

    def __str__(self):
        return f"Audit batch {self.makerspace_id or 'global'}:{self.batch_seq}"


class AuditBatchLeaf(models.Model):
    """Exact immutable membership of an audit batch; an audit row joins once ever."""

    batch = models.ForeignKey(
        AuditBatch,
        on_delete=models.CASCADE,
        related_name="leaves",
    )
    audit_log = models.OneToOneField(
        AuditLog,
        on_delete=models.PROTECT,
        related_name="batch_leaf",
    )
    leaf_position = models.PositiveIntegerField()

    class Meta:
        ordering = ["leaf_position"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "leaf_position"],
                name="uniq_audit_batch_leaf_position",
            ),
        ]

    def __str__(self):
        return f"Audit batch leaf {self.batch_id}:{self.leaf_position}"
