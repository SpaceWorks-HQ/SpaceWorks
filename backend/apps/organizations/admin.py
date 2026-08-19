from django.contrib import admin
from django.core.exceptions import PermissionDenied
from unfold.admin import ModelAdmin, TabularInline

from apps.accounts import rbac
from apps.audit import services as audit
from apps.organizations.models import Organization, OrganizationMakerspace
from config.admin_access import SuperuserOnlyModelAdmin


def _hidden_makerspace_ids():
    return rbac.superadmin_hidden_makerspace_ids()


class OrganizationMakerspaceInline(TabularInline):
    model = OrganizationMakerspace
    fk_name = "organization"
    fields = ("makerspace", "relationship", "created_by", "created_at", "updated_at")
    readonly_fields = ("created_by", "created_at", "updated_at")
    autocomplete_fields = ("makerspace",)
    extra = 0

    def get_queryset(self, request):
        """Hard-hidden makerspaces stay hidden even through a GLOBAL parent.

        Organization resolves as a global model, so this inline does not inherit the
        scoped admin's filtering. Without this, an org linked to a makerspace with
        superadmin_access_enabled=False would expose and allow edits to that link.
        """
        return super().get_queryset(request).exclude(
            makerspace_id__in=_hidden_makerspace_ids()
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Also constrain the CHOICES: an unscoped field queryset would validate a crafted
        # POST naming a hidden makerspace id.
        if db_field.name == "makerspace":
            from apps.makerspaces.models import Makerspace

            kwargs["queryset"] = Makerspace.objects.exclude(
                pk__in=_hidden_makerspace_ids()
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Organization)
class OrganizationAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("name", "slug", "legal_name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "legal_name", "registration_number")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_by", "created_at", "updated_at")
    inlines = (OrganizationMakerspaceInline,)

    def _has_hidden_links(self, obj):
        return OrganizationMakerspace.objects.filter(
            organization=obj, makerspace_id__in=_hidden_makerspace_ids()
        ).exists()

    def has_delete_permission(self, request, obj=None):
        # Deleting the org cascades through OrganizationMakerspace.organization and would
        # remove a link belonging to a hard-hidden tenant.
        if obj is not None and self._has_hidden_links(obj):
            return False
        return super().has_delete_permission(request, obj=obj)

    def get_deleted_objects(self, objs, request):
        """Reject before the preview renders, not after.

        Django calls this ahead of delete_queryset() to build the confirmation page, and
        that page lists related OrganizationMakerspace rows whose __str__ includes the
        makerspace NAME. Guarding only in delete_queryset would still let a superadmin
        reveal a hard-hidden tenant just by selecting its organization for deletion.
        """
        hidden = _hidden_makerspace_ids()
        if OrganizationMakerspace.objects.filter(
            organization__in=[obj.pk for obj in objs] or [None],
            makerspace_id__in=hidden,
        ).exists():
            raise PermissionDenied(
                "One or more organizations link to a hidden makerspace."
            )
        return super().get_deleted_objects(objs, request)

    def delete_queryset(self, request, queryset):
        # `delete_selected` bypasses has_delete_permission per object, so guard bulk too.
        hidden = _hidden_makerspace_ids()
        if OrganizationMakerspace.objects.filter(
            organization__in=queryset, makerspace_id__in=hidden
        ).exists():
            raise PermissionDenied(
                "One or more organizations link to a hidden makerspace."
            )
        super().delete_queryset(request, queryset)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        # Django's admin LogEntry is a separate, unscoped store, so governance changes
        # need an entry in the project's append-only audit log too.
        audit.record(
            request.user,
            "organization.updated" if change else "organization.created",
            target=obj,
            meta={"slug": obj.slug},
        )

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for deleted in formset.deleted_objects:
            makerspace = deleted.makerspace
            relationship = deleted.relationship
            organization_slug = deleted.organization.slug
            deleted.delete()
            audit.record(
                request.user,
                "organization.link_removed",
                makerspace=makerspace,
                target=form.instance,
                meta={
                    "organization_slug": organization_slug,
                    "relationship": relationship,
                },
            )
        for instance in instances:
            created = instance.pk is None
            if isinstance(instance, OrganizationMakerspace) and created:
                instance.created_by = request.user
            instance.save()
            if isinstance(instance, OrganizationMakerspace):
                audit.record(
                    request.user,
                    "organization.link_created" if created
                    else "organization.link_updated",
                    makerspace=instance.makerspace,
                    target=instance,
                    meta={
                        "organization_slug": instance.organization.slug,
                        "relationship": instance.relationship,
                    },
                )
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
        audit.record(
            request.user,
            "organization.link_updated" if change else "organization.link_created",
            makerspace=obj.makerspace,
            target=obj,
            meta={
                "organization_slug": obj.organization.slug,
                "relationship": obj.relationship,
            },
        )
