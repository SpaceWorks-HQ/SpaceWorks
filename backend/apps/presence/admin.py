from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.presence.models import PresenceSession
from apps.separability.tombstones import app_is_tombstoned
from config.admin_access import SuperuserOnlyModelAdmin


class PresenceSessionAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("member", "makerspace", "started_at", "expires_at", "ended_at", "end_reason")
    list_filter = ("makerspace", "end_reason")
    readonly_fields = tuple(field.name for field in PresenceSession._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD") and super().has_change_permission(request, obj)


# Registered rather than decorated: the admin screen is a runtime surface a tombstone
# removes, while the rows stay reachable through the ORM and the purge path. The
# setting is consulted instead of the manifest because admin autodiscovery runs before
# this app's ready(). See separability.tombstones.app_is_tombstoned.
if not app_is_tombstoned("presence"):
    admin.site.register(PresenceSession, PresenceSessionAdmin)
