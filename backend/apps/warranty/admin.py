from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.separability.tombstones import app_is_tombstoned
from apps.warranty.models import Warranty, WarrantyDocument
from config.admin_access import SuperuserOnlyModelAdmin


class WarrantyAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "id",
        "makerspace",
        "host",
        "asset",
        "machine",
        "purchased_on",
        "warranty_expires_on",
        "vendor_name",
    )
    list_filter = ("makerspace",)
    search_fields = (
        "vendor_name",
        "vendor_contact",
        "asset__asset_tag",
        "machine__name",
        "makerspace__name",
        "makerspace__slug",
    )
    raw_id_fields = ("makerspace", "asset", "machine")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Host")
    def host(self, obj):
        if obj.machine_id:
            return obj.machine
        if obj.asset_id:
            return obj.asset
        return None


class WarrantyDocumentAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("id", "warranty", "original_filename", "content_type", "size_bytes", "created_at")
    list_filter = ("content_type",)
    search_fields = ("original_filename", "object_key", "warranty__vendor_name")
    readonly_fields = (
        "warranty",
        "object_key",
        "original_filename",
        "content_type",
        "size_bytes",
        "uploaded_by",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# Registered rather than decorated: the admin screens are runtime surfaces a tombstone
# removes, while the rows stay reachable through the ORM and the purge path. The
# setting is consulted instead of the manifest because admin autodiscovery runs before
# this app's ready(). See separability.tombstones.app_is_tombstoned.
if not app_is_tombstoned("warranty"):
    admin.site.register(Warranty, WarrantyAdmin)
    admin.site.register(WarrantyDocument, WarrantyDocumentAdmin)
