"""Offsite (online) backup destinations and their upload journal.

A destination is a deployment-level, superadmin-managed S3-compatible bucket that
receives copies of the already age-encrypted archives. The journal is the record of
what reached which destination and whether its bytes were read back and matched the
artifact ledger. It deliberately outlives the `BackupArchive` row (SET_NULL plus
immutable snapshots), because retention may delete the primary row while an offsite
copy is still the deployment's only surviving backup.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.makerspaces.secrets import decrypt_value, encrypt_value


class BackupDestination(models.Model):
    class Kind(models.TextChoices):
        S3 = "s3", "S3-compatible (AWS, R2, Supabase Storage, MinIO)"

    class AddressingStyle(models.TextChoices):
        AUTO = "auto", "Auto"
        PATH = "path", "Path"
        VIRTUAL = "virtual", "Virtual host"

    name = models.SlugField(max_length=64, unique=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.S3)
    endpoint_url = models.URLField(max_length=300, blank=True)
    bucket = models.CharField(max_length=255)
    region = models.CharField(max_length=64, blank=True)
    prefix = models.CharField(max_length=200, blank=True)
    addressing_style = models.CharField(
        max_length=16, choices=AddressingStyle.choices, default=AddressingStyle.AUTO
    )
    # Fernet ciphertext (`fernet:` prefix) under API_CLIENT_ENC_KEY, the same
    # at-rest pattern every per-makerspace integration credential uses. Never
    # serialized, logged, audited or exported.
    access_key_id = models.CharField(max_length=500, blank=True)
    secret_access_key = models.CharField(max_length=500, blank=True)
    enabled = models.BooleanField(default=True)
    retention_days = models.PositiveSmallIntegerField(
        default=90, validators=(MinValueValidator(1), MaxValueValidator(3650))
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_backup_destinations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)

    class Meta:
        app_label = "backup"
        ordering = ("name",)

    def __str__(self):
        return f"Backup destination {self.name}"

    def set_access_key_id(self, raw):
        self.access_key_id = encrypt_value(raw) if raw else ""

    def get_access_key_id(self):
        return decrypt_value(self.access_key_id) if self.access_key_id else ""

    def set_secret_access_key(self, raw):
        self.secret_access_key = encrypt_value(raw) if raw else ""

    def get_secret_access_key(self):
        return decrypt_value(self.secret_access_key) if self.secret_access_key else ""

    @property
    def is_active(self):
        return self.enabled and self.retired_at is None


class BackupDestinationUpload(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending upload"
        UPLOADING = "uploading", "Uploading"
        # Named for what the platform can actually prove: the remote ciphertext was
        # read back and equals the ledger's size and SHA-256. It is NOT a claim that
        # the archive restores -- a sealed tenant slice cannot be opened here at all.
        BYTES_VERIFIED = "bytes_verified", "Bytes verified"
        ABANDONED = "abandoned", "Abandoned (source no longer available)"
        DELETED = "deleted", "Deleted by retention"

    class IntegritySource(models.TextChoices):
        ARTIFACT_LEDGER = "artifact_ledger", "Artifact ledger"
        ARCHIVE_ROW = "archive_row", "Archive row"

    destination = models.ForeignKey(
        BackupDestination, on_delete=models.PROTECT, related_name="uploads"
    )
    archive = models.ForeignKey(
        "backup.BackupArchive",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="offsite_uploads",
    )
    archive_id_snapshot = models.UUIDField()
    scope_snapshot = models.CharField(max_length=16)
    makerspace_id_snapshot = models.BigIntegerField(null=True, blank=True)
    format_snapshot = models.CharField(max_length=80, blank=True)
    archive_completed_at_snapshot = models.DateTimeField()
    expected_size_bytes = models.PositiveBigIntegerField()
    expected_sha256 = models.CharField(max_length=64)
    integrity_source = models.CharField(max_length=24, choices=IntegritySource.choices)
    # A locator on the REMOTE destination, never a key in this deployment's buckets.
    remote_locator = models.CharField(max_length=600)
    state = models.CharField(max_length=24, choices=State.choices, default=State.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    holder = models.UUIDField(null=True, blank=True)
    claimed_until = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    verified_sha256 = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "backup"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("destination", "archive_id_snapshot"),
                name="uniq_backup_destination_archive",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(state="bytes_verified")
                    | models.Q(verified_at__isnull=False, verified_size_bytes__isnull=False)
                ),
                name="backup_offsite_verified_facts",
            ),
        ]
        indexes = [
            models.Index(fields=("state", "next_attempt_at"), name="backup_offsite_due_idx"),
        ]
