from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.accounts import rbac
from apps.audit import services as audit
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

    def resolve_hidden_lookup(self):
        return "event__makerspace_id"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "event":
            kwargs["queryset"] = Event.objects.exclude(
                makerspace_id__in=rbac.superadmin_hidden_makerspace_ids()
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        audit.record(
            request.user,
            "event.organizer_updated" if change else "event.organizer_created",
            makerspace=obj.event.makerspace,
            target=obj,
            meta={
                "event_id": obj.event_id,
                "organization_slug": obj.organization.slug,
            },
        )

    def delete_model(self, request, obj):
        self._record_deletion(request, obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset.select_related("event__makerspace", "organization"):
            self._record_deletion(request, obj)
        super().delete_queryset(request, queryset)

    @staticmethod
    def _record_deletion(request, obj):
        audit.record(
            request.user,
            "event.organizer_deleted",
            makerspace=obj.event.makerspace,
            target=obj,
            meta={
                "event_id": obj.event_id,
                "organization_slug": obj.organization.slug,
            },
        )


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

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        for event in obj.series.occurrences.all():
            EventOrganizer.objects.get_or_create(
                event=event,
                organization=obj.organization,
                defaults={"created_by": request.user, "source_series_organizer": obj},
            )
        audit.record(
            request.user,
            "event.series_organizer_created" if not change else "event.series_organizer_updated",
            makerspace=obj.series.makerspace,
            target=obj,
            meta={"series_id": obj.series_id, "organization_slug": obj.organization.slug},
        )

    def delete_model(self, request, obj):
        EventOrganizer.objects.filter(source_series_organizer=obj).delete()
        audit.record(
            request.user, "event.series_organizer_deleted",
            makerspace=obj.series.makerspace, target=obj,
            meta={"series_id": obj.series_id, "organization_slug": obj.organization.slug},
        )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset.select_related("series__makerspace", "organization"):
            EventOrganizer.objects.filter(source_series_organizer=obj).delete()
            audit.record(
                request.user, "event.series_organizer_deleted",
                makerspace=obj.series.makerspace, target=obj,
                meta={"series_id": obj.series_id, "organization_slug": obj.organization.slug},
            )
        super().delete_queryset(request, queryset)


if not app_is_tombstoned("events"):
    admin.site.register(EventOrganizer, EventOrganizerAdmin)
    admin.site.register(EventSeriesOrganizer, EventSeriesOrganizerAdmin)
