from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.organizations.models import Organization, OrganizationMakerspace
from config.admin_access import SuperuserOnlyModelAdmin


class OrganizationMakerspaceInline(TabularInline):
    model = OrganizationMakerspace
    fk_name = "organization"
    fields = ("makerspace", "relationship", "created_by", "created_at", "updated_at")
    readonly_fields = ("created_by", "created_at", "updated_at")
    autocomplete_fields = ("makerspace",)
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("name", "slug", "legal_name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "legal_name", "registration_number")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_by", "created_at", "updated_at")
    inlines = (OrganizationMakerspaceInline,)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for deleted in formset.deleted_objects:
            deleted.delete()
        for instance in instances:
            if isinstance(instance, OrganizationMakerspace) and instance.pk is None:
                instance.created_by = request.user
            instance.save()
        formset.save_m2m()


@admin.register(OrganizationMakerspace)
class OrganizationMakerspaceAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "organization",
        "makerspace",
        "relationship",
        "created_by",
        "created_at",
    )
    list_filter = ("relationship", "makerspace")
    search_fields = ("organization__name", "organization__slug", "makerspace__name")
    autocomplete_fields = ("organization", "makerspace")
    readonly_fields = ("created_by", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
