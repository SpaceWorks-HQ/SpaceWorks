from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.accounts import rbac
from apps.events.models import Event, EventOrganizer
from apps.separability.tombstones import app_is_tombstoned
from config.admin_access import SuperuserOnlyModelAdmin


class EventOrganizerAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("event", "organization", "created_by", "created_at")
    list_filter = ("event__makerspace", "organization")
    search_fields = (
        "event__title",
        "event__makerspace__name",
        "organization__name",
        "organization__slug",
    )
    readonly_fields = ("created_by", "created_at")

    # Organizer mutations now have one transaction boundary in
    # services_organizers.replace_organizers. Keeping the old per-row admin writer would
    # bypass its event/module locks and its single replacement audit record.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def resolve_hidden_lookup(self):
        return "event__makerspace_id"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "event":
            kwargs["queryset"] = Event.objects.exclude(
                makerspace_id__in=rbac.superadmin_hidden_makerspace_ids()
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

if not app_is_tombstoned("events"):
    admin.site.register(EventOrganizer, EventOrganizerAdmin)
