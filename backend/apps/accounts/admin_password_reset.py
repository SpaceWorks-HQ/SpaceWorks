from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.accounts.models_password_reset import PasswordResetEnvelope
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(PasswordResetEnvelope)
class PasswordResetEnvelopeAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """Operational visibility without exposing digests or writable workflow state."""

    list_display = (
        "email_normalized",
        "status",
        "generation",
        "requested_at",
        "terminal_at",
    )
    list_filter = ("status",)
    search_fields = ("email_normalized", "email_fingerprint", "claim_owner")
    fields = (
        "email_normalized",
        "email_fingerprint",
        "user",
        "status",
        "attempts",
        "generation",
        "requested_at",
        "expires_at",
        "consumed_at",
        "claimed_at",
        "claim_owner",
        "claim_expires_at",
        "superseded_at",
        "terminal_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
