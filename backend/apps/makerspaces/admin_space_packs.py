"""Control-plane discovery; profiles are created through the audited API."""
from django.contrib import admin
from unfold.admin import ModelAdmin

from config.admin_access import SuperuserOnlyModelAdmin
from .models import SpacePackProfile


@admin.register(SpacePackProfile)
class SpacePackProfileAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("name", "created_at", "updated_at")
    readonly_fields = ("name", "pack", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
