from django.db import connection, models
from django.db.models import Q
from django.core.exceptions import ValidationError


class EncryptionKeyQuerySet(models.QuerySet):
    def delete(self):
        raise RuntimeError("Encryption key rows cannot be deleted.")


class EncryptionKeyManager(models.Manager.from_queryset(EncryptionKeyQuerySet)):
    pass


class MakerspaceEncryptionKey(models.Model):
    class BrokerBackend(models.TextChoices):
        LOCAL = "local", "Local master key"
        AWS_KMS = "aws_kms", "AWS KMS"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ROTATED = "rotated", "Rotated"
        DISABLED = "disabled", "Disabled"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.PROTECT,
        related_name="encryption_keys",
    )
    version = models.PositiveIntegerField()
    wrapped_dek = models.BinaryField()
    broker_backend = models.CharField(max_length=16, choices=BrokerBackend.choices)
    broker_key_id = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    rotated_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)

    objects = EncryptionKeyManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "version"], name="uniq_makerspace_dek_version"
            ),
            models.UniqueConstraint(
                fields=["makerspace"],
                condition=Q(status="active"),
                name="uniq_makerspace_active_dek",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="ck_makerspace_dek_version_positive"
            ),
        ]
        indexes = [models.Index(fields=["makerspace", "status"])]

    def delete(self, *args, **kwargs):
        raise RuntimeError("Encryption key rows cannot be deleted.")


class SearchKeyGeneration(models.Model):
    """Non-secret provenance for the one search HMAC material in service."""

    class Status(models.TextChoices):
        BUILDING = "building", "Building"
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    generation = models.PositiveIntegerField(primary_key=True)
    key_fingerprint = models.BinaryField(max_length=32, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(generation__gte=1), name="ck_search_generation_positive"),
            models.UniqueConstraint(fields=["status"], condition=Q(status="active"), name="uniq_active_search_generation"),
        ]


class PiiBlindIndex(models.Model):
    """Tenant-scoped, generation-bound candidates; never a source of truth."""

    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    model_label = models.CharField(max_length=96)
    object_id = models.BigIntegerField()
    field_name = models.CharField(max_length=64)
    search_generation = models.ForeignKey(SearchKeyGeneration, on_delete=models.PROTECT)
    bloom_bits = models.BinaryField(max_length=256)
    exact_hash = models.BinaryField(max_length=32, null=True, blank=True)
    algorithm_version = models.PositiveSmallIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["makerspace", "model_label", "object_id", "field_name"], name="uniq_pii_blind_index_source_field"),
            models.CheckConstraint(condition=Q(algorithm_version=1), name="ck_pii_blind_index_algorithm_v1"),
        ]
        indexes = [
            models.Index(fields=["makerspace", "model_label", "field_name"]),
            models.Index(fields=["search_generation", "makerspace", "model_label", "field_name", "exact_hash"], name="pii_bi_generation_exact_idx"),
        ]

    def clean(self):
        allowed = {
            (field.model_label, field.field_name): field.index_kind
            for field in __import__("apps.encryption.registry", fromlist=["all_fields"]).all_fields()
            if field.index_kind in {"bloom", "bloom_exact"}
        }
        kind = allowed.get((self.model_label, self.field_name))
        if kind is None or len(bytes(self.bloom_bits or b"")) != 256:
            raise ValidationError("Invalid scoped PII blind-index row.")
        if (kind == "bloom_exact") != (self.exact_hash is not None):
            raise ValidationError("Invalid scoped PII exact-hash shape.")
        if self.exact_hash is not None and len(bytes(self.exact_hash)) != 32:
            raise ValidationError("Invalid scoped PII exact-hash shape.")

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class _FenceQuerySet(models.QuerySet):
    def delete(self):
        if not self.model._purge_delete_allowed():
            raise RuntimeError("PII write-fence rows cannot be deleted.")
        return super().delete()


class _FenceModel(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    class OperationKind(models.TextChoices):
        ENABLE_TRANSITION = "enable_transition", "Enable transition"
        DECRYPT_ROLLBACK = "decrypt_rollback", "Decrypt rollback"
        SEARCH_ROTATION = "search_rotation", "Search rotation"

    state = models.CharField(max_length=8, choices=State.choices, default=State.OPEN)
    operation_id = models.UUIDField(null=True, blank=True)
    operation_kind = models.CharField(
        max_length=20, choices=OperationKind.choices, null=True, blank=True
    )
    actor_id = models.BigIntegerField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)

    objects = _FenceQuerySet.as_manager()

    class Meta:
        abstract = True

    @classmethod
    def _purge_delete_allowed(cls):
        return False

    def delete(self, *args, **kwargs):
        if not self._purge_delete_allowed():
            raise RuntimeError("PII write-fence rows cannot be deleted.")
        return super().delete(*args, **kwargs)


class PiiGlobalWriteFence(_FenceModel):
    """The fixed-ID global fence; id=1 makes a second singleton impossible."""

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(pk=1), name="ck_pii_global_fence_singleton")]


class PiiMakerspaceWriteFence(_FenceModel):
    makerspace = models.OneToOneField(
        "makerspaces.Makerspace",
        on_delete=models.PROTECT,
        related_name="pii_write_fence",
    )

    @classmethod
    def _purge_delete_allowed(cls):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('app.allow_immutable_delete', true)")
            return cursor.fetchone()[0] == "on"
