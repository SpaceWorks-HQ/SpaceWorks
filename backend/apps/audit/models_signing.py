"""Signing-key and batch-attestation models."""

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
    """Deployment-local Ed25519 authority for one audit scope."""

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="audit_signing_keys",
    )
    wrapped_private_key = models.BinaryField()
    public_key = models.BinaryField()
    fingerprint = models.CharField(max_length=64)
    activation_payload = models.JSONField(default=dict)
    activation_signature = models.BinaryField()
    created_at = models.DateTimeField(default=timezone.now)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace"],
                nulls_distinct=False,
                name="uniq_audit_signing_key_scope",
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
        return f"Audit signing key for makerspace {self.makerspace_id or 'global'}"


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
