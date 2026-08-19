from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.audit.models import (
    AuditBatch,
    AuditBatchLeaf,
    AuditLog,
    AuditMacKey,
    AuditSigningKey,
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
    list_display = ("makerspace", "fingerprint", "created_at", "activated_at")
    list_filter = ("makerspace", "created_at", "activated_at")
    exclude = ("wrapped_private_key", "activation_signature")
    readonly_fields = (
        "makerspace",
        "public_key",
        "fingerprint",
        "activation_payload",
        "created_at",
        "activated_at",
    )


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
