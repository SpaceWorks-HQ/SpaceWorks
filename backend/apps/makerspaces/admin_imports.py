from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.makerspaces.models import (
    ImportedUserReconciliation,
    PendingImportedMembership,
)
from config.admin_access import SuperuserOnlyModelAdmin


class ReadOnlyImportStateAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD") and super().has_change_permission(
            request, obj
        )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PendingImportedMembership)
class PendingImportedMembershipAdmin(ReadOnlyImportStateAdmin):
    list_display = (
        "email",
        "makerspace",
        "status",
        "source_membership_id",
        "adopted_at",
        "unresolved_reason",
    )
    list_filter = ("makerspace", "status", "unresolved_reason")
    search_fields = ("email", "source_membership_id")
    readonly_fields = tuple(field.name for field in PendingImportedMembership._meta.fields)


@admin.register(ImportedUserReconciliation)
class ImportedUserReconciliationAdmin(ReadOnlyImportStateAdmin):
    list_display = (
        "makerspace",
        "source_user_id",
        "source_username",
        "target_user",
        "created_at",
    )
    list_filter = ("makerspace",)
    search_fields = ("source_user_id", "source_username", "target_user__username")
    readonly_fields = tuple(field.name for field in ImportedUserReconciliation._meta.fields)
