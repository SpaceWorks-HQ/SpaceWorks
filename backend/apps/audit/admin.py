from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.audit.models import (
    AuditBatch,
    AuditBatchLeaf,
    AuditLog,
    AuditMacKey,
    AuditSigningKey,
    AuditSigningKeyRotation,
    AuditSigningKeyRotationEvent,
)
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(AuditLog)
class AuditLogAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "created_at",
        "actor",
        "action",
        "makerspace",
        "target_type",
        "target_id",
    )
    list_filter = ("action", "makerspace", "created_at")
    search_fields = (
        "action",
        "target_type",
        "target_id",
        "actor__username",
        "actor__email",
        "makerspace__name",
        "makerspace__slug",
    )
    readonly_fields = (
        "event_uuid",
        "actor",
        "action",
        "target_type",
        "target_id",
        "makerspace",
        "meta",
        "row_mac",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditMacKey)
class AuditMacKeyAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("makerspace", "created_at")
    list_filter = ("makerspace", "created_at")
    readonly_fields = ("makerspace", "created_at")
    exclude = ("wrapped_key",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class _ReadOnlyAuditAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditSigningKey)
class AuditSigningKeyAdmin(_ReadOnlyAuditAdmin):
    list_display = (
        "makerspace", "version", "fingerprint", "is_active", "valid_from_seq",
        "valid_to_seq", "created_at", "activated_at",
    )
    list_filter = ("makerspace", "is_active", "created_at", "activated_at")
    exclude = ("wrapped_private_key", "activation_signature")
    readonly_fields = (
        "makerspace",
        "public_key",
        "fingerprint",
        "version",
        "valid_from_seq",
        "valid_to_seq",
        "is_active",
        "pending_rotation",
        "activation_payload",
        "created_at",
        "activated_at",
    )


@admin.register(AuditSigningKeyRotation)
class AuditSigningKeyRotationAdmin(_ReadOnlyAuditAdmin):
    list_display = (
        "id", "makerspace", "old_version", "new_version",
        "last_old_batch_seq", "created_at",
    )
    list_filter = ("makerspace", "created_at")
    readonly_fields = (
        "id", "makerspace", "old_key", "new_key", "old_fingerprint",
        "new_fingerprint", "old_version", "new_version", "last_old_batch_seq",
        "last_old_batch_root", "payload", "old_signature", "new_signature",
        "created_at",
    )


@admin.register(AuditSigningKeyRotationEvent)
class AuditSigningKeyRotationEventAdmin(_ReadOnlyAuditAdmin):
    list_display = ("rotation", "state", "created_at")
    list_filter = ("state", "created_at")
    readonly_fields = ("rotation", "state", "created_at")

    def resolve_hidden_lookup(self):
        # The event row carries only the transition state; scope comes from its rotation.
        # Without this a superadmin who hid a makerspace would still see that space's
        # rotation history in /control/ -- the same hide-scoping hole ORG-2b closed for
        # OrganizationMembership. The model also reaches Makerspace through
        # rotation__old_key and rotation__new_key; the rotation's own FK is the canonical
        # one, since both keys belong to that scope by construction.
        return "rotation__makerspace_id"


@admin.register(AuditBatch)
class AuditBatchAdmin(_ReadOnlyAuditAdmin):
    list_display = ("makerspace", "batch_seq", "leaf_count", "created_at")
    list_filter = ("makerspace", "created_at")
    readonly_fields = (
        "makerspace",
        "batch_seq",
        "leaf_count",
        "merkle_root",
        "prev_batch_root",
        "created_at",
        "signature",
        "signer_fingerprint",
    )


@admin.register(AuditBatchLeaf)
class AuditBatchLeafAdmin(_ReadOnlyAuditAdmin):
    list_display = ("batch", "audit_log", "leaf_position")
    list_filter = ("batch__makerspace",)
    readonly_fields = ("batch", "audit_log", "leaf_position")

    def resolve_hidden_lookup(self):
        # The leaf intentionally stores only exact membership coordinates. Scope comes
        # from its batch; keep that fact local instead of growing the global registry.
        return "batch__makerspace_id"
