from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.accounts.models_claim import MemberClaimCode
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(MemberClaimCode)
class MemberClaimCodeAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """Read-only credential lifecycle metadata; the digest is deliberately hidden."""

    fields = (
        "membership",
        "issued_by",
        "issued_at",
        "expires_at",
        "consumed_at",
        "consumed_ip",
        "failed_attempts",
        "revoked_at",
        "revoked_by",
        "session_id",
    )
    readonly_fields = fields
    list_display = (
        "id",
        "membership",
        "issued_by",
        "issued_at",
        "expires_at",
        "consumed_at",
        "revoked_at",
    )
    list_filter = ("membership__makerspace",)
    search_fields = (
        "membership__user__username",
        "membership__user__display_name",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

