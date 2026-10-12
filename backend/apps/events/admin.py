from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.accounts import rbac
from apps.events import services_series_organizers
from apps.events.models import Event, EventOrganizer, EventSeries, EventSeriesOrganizer
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


# NOTE: the events side also re-added save_model/delete_model to EventOrganizerAdmin.
# They are dropped here: phase 7 turned that admin read-only on purpose, so those
# methods are unreachable and would only mislead a future reader.
class EventSeriesOrganizerAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("series", "organization", "created_by", "created_at")
    list_filter = ("series__makerspace", "organization")
    search_fields = ("series__title", "series__makerspace__name", "organization__name")
    readonly_fields = ("created_by", "created_at")

    def resolve_hidden_lookup(self):
        return "series__makerspace_id"

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return (*fields, "series", "organization") if obj else fields

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "series":
            kwargs["queryset"] = EventSeries.objects.exclude(
                makerspace_id__in=rbac.superadmin_hidden_makerspace_ids()
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # Superadmin operations route through services, never the ORM: the service takes the
    # series row lock and the events module lock, checks authority, projects the organizer
    # onto every occurrence and writes the audit entry. The admin only chooses the rows.
    def save_model(self, request, obj, form, change):
        services_series_organizers.add_series_organizer(
            obj.series, actor=request.user, organization=obj.organization
        )

    def delete_model(self, request, obj):
        services_series_organizers.remove_series_organizer(obj, actor=request.user)

    def delete_queryset(self, request, queryset):
        for obj in queryset.select_related("series__makerspace", "organization"):
            services_series_organizers.remove_series_organizer(obj, actor=request.user)


if not app_is_tombstoned("events"):
    admin.site.register(EventOrganizer, EventOrganizerAdmin)
    admin.site.register(EventSeriesOrganizer, EventSeriesOrganizerAdmin)
