from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.notifications.models import Notification
from apps.separability.tombstones import app_is_tombstoned
from config.admin_access import SuperuserOnlyModelAdmin


class NotificationAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("title", "level", "event", "makerspace", "read_at", "created_at")
    list_filter = ("makerspace", "level", "read_at")
    search_fields = ("title", "body", "event", "makerspace__name", "makerspace__slug")
    readonly_fields = ("created_at",)


# Registered rather than decorated: the admin screen is a runtime surface, and the
# setting is consulted instead of the manifest because admin autodiscovery runs
# before this app's ready(). See separability.tombstones.app_is_tombstoned.
if not app_is_tombstoned("notifications"):
    admin.site.register(Notification, NotificationAdmin)