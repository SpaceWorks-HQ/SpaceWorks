import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.apiclients.crypto import decrypt_secret, encrypt_secret
from apps.makerspaces.models import Makerspace


def generate_client_id():
    return f"ck_{secrets.token_urlsafe(18)}"


class ApiClient(models.Model):
    """A signed API client (client_id + HMAC secret) scoped to a makerspace.

    Secret is stored ENCRYPTED (Fernet), not hashed - HMAC verification needs the raw
    secret back. `makerspace=None` is a global client (superadmin only)."""

    label = models.CharField(max_length=200)
    client_id = models.CharField(
        max_length=64, unique=True, default=generate_client_id, editable=False
    )
    secret_encrypted = models.BinaryField(editable=False)
    previous_secret_encrypted = models.BinaryField(
        null=True,
        blank=True,
        editable=False,
    )
    previous_secret_valid_until = models.DateTimeField(null=True, blank=True)
    client_type = models.CharField(
        max_length=20,
        choices=[
            ("browser", "Browser"),
            ("server", "Server"),
        ],
        default="server",
    )
    scopes = models.JSONField(default=list, blank=True)
    rate_limit_tier = models.CharField(
        max_length=20,
        choices=[
            ("public", "Public"),
            ("standard", "Standard"),
            ("trusted", "Trusted"),
        ],
        default="standard",
    )
    makerspace = models.ForeignKey(
        Makerspace, null=True, blank=True, on_delete=models.CASCADE,
        related_name="api_clients",
    )
    allowed_origins = models.JSONField(default=list, blank=True)  # exact scheme://host[:port]
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_api_clients",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_ip = models.GenericIPAddressField(null=True, blank=True)
    import_provenance_digest = models.CharField(
        max_length=64, null=True, blank=True, unique=True, editable=False
    )
    credential_delivered_at = models.DateTimeField(null=True, blank=True, editable=False)

    def save(self, *args, **kwargs):
        # Centralised here, not only in issue(): the /control/ ModelAdmin and
        # seed_demo._sync_legacy_hmac_client() construct rows directly, and an empty
        # scopes list is now DENIED by the authoritative registry -- those clients would
        # 401 on every protected route with no way to repair them from the admin.
        if not self.scopes:
            from apps.apiclients.scope_registry import LEGACY_SCOPE

            self.scopes = [LEGACY_SCOPE]
        super().save(*args, **kwargs)

    def set_secret(self, raw):
        self.secret_encrypted = encrypt_secret(raw)

    def get_secret(self):
        return decrypt_secret(self.secret_encrypted)

    def clean(self):
        # review fix #4: an HMAC client must restrict to at least one exact origin.
        from django.core.exceptions import ValidationError

        from apps.apiclients.origin_validation import validate_exact_origins

        try:
            self.allowed_origins = validate_exact_origins(self.allowed_origins)
        except ValueError as exc:
            raise ValidationError({"allowed_origins": str(exc)}) from exc

    @classmethod
    def issue(
        cls,
        *,
        label,
        scopes,
        makerspace=None,
        allowed_origins=None,
        created_by=None,
        client_type="browser",
        rate_limit_tier="standard",
        raw_secret=None,
        import_provenance_digest=None,
    ):
        raw = raw_secret or secrets.token_urlsafe(32)
        issued_scopes = list(scopes or [])
        if not issued_scopes:
            raise ValidationError(
                {"scopes": "At least one API-client scope is required."}
            )
        obj = cls(
            label=label,
            makerspace=makerspace,
            allowed_origins=allowed_origins or [],
            created_by=created_by,
            client_type=client_type,
            scopes=issued_scopes,
            rate_limit_tier=rate_limit_tier,
            import_provenance_digest=import_provenance_digest,
        )
        obj.set_secret(raw)
        obj.full_clean()
        obj.save()
        return obj, raw  # raw secret shown to the operator exactly once

    def __str__(self):
        return f"{self.label} ({self.client_id})"


class ApiKeyRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.CASCADE,
        related_name="api_key_requests",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="api_key_requests",
    )
    label = models.CharField(max_length=120)
    reason = models.TextField(blank=True)
    allowed_origins = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    resolution_note = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_api_key_requests",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} ({self.status})"


class ApiClientImportApproval(models.Model):
    """Immutable, artifact-bound authorization for one Lane D client reset."""

    makerspace = models.ForeignKey(
        Makerspace, on_delete=models.PROTECT, related_name="api_client_import_approvals"
    )
    api_client = models.OneToOneField(
        ApiClient, on_delete=models.PROTECT, related_name="import_approval"
    )
    artifact_sha256 = models.CharField(max_length=64)
    capture_id = models.UUIDField()
    source_catalog_sha256 = models.CharField(max_length=64)
    source_client_ref = models.CharField(max_length=64)
    source_entry_sha256 = models.CharField(max_length=64)
    approval_record_sha256 = models.CharField(max_length=64, unique=True)
    host_principal = models.CharField(max_length=255)
    approval_nonce = models.CharField(max_length=64, unique=True)
    approved_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("API-client import approvals are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("API-client import approvals are append-only.")
