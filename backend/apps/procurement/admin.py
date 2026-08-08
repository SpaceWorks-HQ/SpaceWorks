from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.procurement.models import ToBuyItem, ToBuyReceipt
from apps.separability.tombstones import app_is_tombstoned
from config.admin_access import SuperuserOnlyModelAdmin


class ToBuyItemAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "name",
        "makerspace",
        "kind",
        "quantity",
        "status",
        "vendor_name",
        "purchaser",
        "created_by",
        "created_at",
    )
    list_filter = ("kind", "status", "makerspace")
    search_fields = ("name", "link", "vendor_name", "makerspace__name", "makerspace__slug")
    readonly_fields = ("created_by", "purchaser", "ordered_at", "received_at", "created_at", "updated_at")
    fields = (
        "makerspace",
        "kind",
        "name",
        "quantity",
        "link",
        "status",
        "estimated_unit_cost",
        "vendor_name",
        "actual_unit_cost",
        "purchaser",
        "ordered_at",
        "received_at",
        "created_by",
        "created_at",
        "updated_at",
    )


class ToBuyReceiptAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("id", "to_buy_item", "uploaded_by", "created_at")
    search_fields = ("object_key", "to_buy_item__name", "to_buy_item__makerspace__name")
    readonly_fields = ("to_buy_item", "object_key", "uploaded_by", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# Registered rather than decorated, because the admin surface is exactly what a
# tombstone removes: the rows are retained and still reachable through the ORM and
# the purge path, but the deployment does not offer a screen for a module it no
# longer ships. The classes stay defined either way so the module still imports.
if not app_is_tombstoned("procurement"):
    admin.site.register(ToBuyItem, ToBuyItemAdmin)
    admin.site.register(ToBuyReceipt, ToBuyReceiptAdmin)
