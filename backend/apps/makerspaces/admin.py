from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.exceptions import ValidationError
from django.template.response import TemplateResponse
from unfold.admin import ModelAdmin, TabularInline

from apps.makerspaces.admin_capabilities import MakerspaceAdminForm, MakerspaceCapabilityAdminMixin
from apps.makerspaces.admin_images import MakerspaceImageAdminMixin
from apps.makerspaces.admin_subdomains import SubdomainRequestAdmin
from apps.makerspaces.admin_archive_requests import MakerspaceArchiveRequestAdmin
from apps.makerspaces.admin_imports import (  # noqa: F401
    ImportedUserReconciliationAdmin,
    PendingImportedMembershipAdmin,
)
from apps.makerspaces.models import (
    Makerspace, MakerspaceArchiveRequest, MakerspaceMembership, MakerspaceWaiver, MemberProfile, MemberProject,
    MembershipRequest,
)
from config.admin_access import SuperuserOnlyModelAdmin


class ArchivedFilter(admin.SimpleListFilter):
    title = "archived"
    parameter_name = "archived"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Yes"),
            ("no", "No"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(archived_at__isnull=False)
        if self.value() == "no":
            return queryset.filter(archived_at__isnull=True)
        return queryset


class MakerspaceMembershipInline(TabularInline):
    model = MakerspaceMembership
    fk_name = "makerspace"
    fields = ("user", "role")
    autocomplete_fields = ("user",)
    extra = 0

    def has_view_permission(self, request, obj=None):
        if obj is not None and not obj.superadmin_access_enabled:
            return False
        return super().has_view_permission(request, obj)


@admin.register(Makerspace)
class MakerspaceAdmin(MakerspaceImageAdminMixin, MakerspaceCapabilityAdminMixin, SuperuserOnlyModelAdmin, ModelAdmin):
    form = MakerspaceAdminForm
    actions = ["archive_makerspaces", "unarchive_makerspaces", "purge_makerspaces"]
    list_display = (
        "name",
        "public_code",
        "slug",
        "location",
        "public_inventory_enabled",
        "superadmin_access",
        "frontend_domain",
        "hidden_from_central_directory",
        "frontend_mode",
        "archived",
        "updated_at",
    )
    list_filter = ("public_inventory_enabled", "superadmin_access_enabled", ArchivedFilter)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "public_code", "slug", "location")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "public_code",
                    "slug",
                    "location",
                    "public_inventory_enabled",
                    "public_stats_enabled",
                    "public_stats_show_holder_names",
                    "frontend_domain",
                    "hidden_from_central_directory",
                    "default_loan_days",
                )
            },
        ),
        (
            "Capabilities",
            {"fields": ("capabilities",)},
        ),
        (
            "Public images",
            {
                "fields": (
                    "logo_preview",
                    "logo_upload",
                    "clear_logo",
                    "cover_preview",
                    "cover_upload",
                    "clear_cover",
                )
            },
        ),
    )
    readonly_fields = ("logo_preview", "cover_preview")
    inlines = (MakerspaceMembershipInline,)

    def save_model(self, request, obj, form, change):
        """Initialise archive-custody state for makerspaces created via /control/.

        The control-plane admin saves the model directly, so it never reaches the
        admin-API serializer that seeds this row. Without it a new makerspace has no
        custody state, which makes readiness UNDERCOUNT below-floor spaces and the API
        return null until some later recipient mutation happens to create it.
        """
        super().save_model(request, obj, form, change)
        if not change:
            from apps.backup.custody import initialize_custody_state

            initialize_custody_state(obj.pk)

    def has_change_permission(self, request, obj=None):
        if obj is not None and not obj.superadmin_access_enabled:
            return False
        return super().has_change_permission(request, obj)

    def get_inline_instances(self, request, obj=None):
        if obj is not None and not obj.superadmin_access_enabled:
            return []
        return super().get_inline_instances(request, obj)

    def has_delete_permission(self, request, obj=None):
        # The normal admin delete button is a permanent purge entry point. Keep it
        # object-scoped so the default bulk delete action stays disabled; bulk
        # purges must use the slug-confirming `purge_makerspaces` action below.
        if obj is None:
            return False
        return super().has_delete_permission(request, obj) and obj.archived_at is not None

    def get_deleted_objects(self, objs, request):
        # Django's stock collector asks every related ModelAdmin whether it can
        # delete each related object. Several of those admins intentionally
        # disable ordinary deletes to preserve history, which blocks a whole-space
        # purge even though lifecycle.purge() deletes the complete graph safely.
        objs = list(objs)
        return (
            [f"{self.opts.verbose_name}: {obj}" for obj in objs],
            {self.opts.verbose_name_plural: len(objs)},
            set(),
            [],
        )

    def delete_model(self, request, obj):
        from apps.makerspaces import lifecycle

        lifecycle.purge(obj, request.user)

    @admin.display(boolean=True, description="Archived")
    def archived(self, obj):
        return obj.archived_at is not None

    @admin.display(description="Superadmin access")
    def superadmin_access(self, obj):
        return "Yes" if obj.superadmin_access_enabled else "No"

    @admin.display(description="Frontend mode")
    def frontend_mode(self, obj):
        return "single-tenant" if obj.frontend_domain else "central"

    @admin.action(description="Archive selected makerspaces")
    def archive_makerspaces(self, request, queryset):
        from apps.makerspaces import lifecycle

        makerspaces = list(queryset)
        if "confirm_archive" not in request.POST:
            pending_by_makerspace = {
                archive_request.makerspace_id: archive_request
                for archive_request in MakerspaceArchiveRequest.objects.filter(
                    makerspace__in=makerspaces,
                    status=MakerspaceArchiveRequest.Status.PENDING,
                ).select_related("requested_by")
            }
            context = {
                **self.admin_site.each_context(request),
                "title": "Archive selected makerspaces",
                "makerspaces": [
                    {
                        "object": makerspace,
                        "pending_archive_request": pending_by_makerspace.get(makerspace.pk),
                        **lifecycle.archive_impact(makerspace),
                    }
                    for makerspace in makerspaces
                ],
                "opts": self.model._meta,
                "action_name": "archive_makerspaces",
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(
                request,
                "admin/makerspaces/archive_confirmation.html",
                context,
            )

        for makerspace in makerspaces:
            try:
                lifecycle.archive(makerspace, request.user)
            except ValidationError as err:
                self.message_user(
                    request,
                    f"{makerspace.name} ({makerspace.slug}): {str(err)}",
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"Archived makerspace {makerspace.name} ({makerspace.slug}).",
                    level=messages.SUCCESS,
                )

    @admin.action(description="Unarchive selected makerspaces")
    def unarchive_makerspaces(self, request, queryset):
        from apps.makerspaces import lifecycle

        for makerspace in list(queryset):
            try:
                lifecycle.unarchive(makerspace, request.user)
            except ValidationError as err:
                self.message_user(
                    request,
                    f"{makerspace.name} ({makerspace.slug}): {str(err)}",
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"Unarchived makerspace {makerspace.name} ({makerspace.slug}).",
                    level=messages.SUCCESS,
                )

    @admin.action(description="Purge selected archived makerspaces")
    def purge_makerspaces(self, request, queryset):
        makerspaces = list(queryset)
        if "confirm_purge" not in request.POST:
            context = {
                **self.admin_site.each_context(request),
                "title": "Purge selected makerspaces",
                "queryset": makerspaces,
                "opts": self.model._meta,
                "action_name": "purge_makerspaces",
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(
                request,
                "admin/makerspaces/purge_confirmation.html",
                context,
            )

        from apps.makerspaces import lifecycle

        for makerspace in makerspaces:
            if request.POST.get(f"slug_{makerspace.pk}", "") != makerspace.slug:
                self.message_user(
                    request,
                    f"{makerspace.name} ({makerspace.slug}): slug confirmation did not match",
                    level=messages.ERROR,
                )
                continue

            name = makerspace.name
            slug = makerspace.slug
            try:
                lifecycle.purge(makerspace, request.user)
            except ValidationError as err:
                self.message_user(
                    request,
                    f"{name} ({slug}): {str(err)}",
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    f"Purged makerspace {name} ({slug}).",
                    level=messages.SUCCESS,
                )
        return None


@admin.register(MakerspaceMembership)
class MakerspaceMembershipAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("user", "makerspace", "role", "created_at")
    list_filter = ("makerspace", "role")
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user", "makerspace")
    readonly_fields = (
        "can_refer", "can_verify", "verified_at", "verified_by", "verified_actor_snapshot",
        "activated_actor_snapshot", "revoked_actor_snapshot",
        "waiver_accepted_at", "waiver_version_accepted", "accepted_waiver",
        "witnessed_at", "witnessed_waiver_version", "witnessed_waiver",
        "witnessed_by", "witnessed_actor_snapshot", "created_at",
    )


@admin.register(MakerspaceWaiver)
class MakerspaceWaiverAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("makerspace", "version", "is_active", "created_at", "superseded_at")
    readonly_fields = ("makerspace", "body", "version", "is_active", "created_by", "created_at", "superseded_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD") and super().has_change_permission(request, obj)


@admin.register(MembershipRequest)
class MembershipRequestAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("makerspace", "kind", "state", "user", "invite_email", "created_at")
    readonly_fields = tuple(field.name for field in MembershipRequest._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD") and super().has_change_permission(request, obj)


@admin.register(MemberProfile)
class MemberProfileAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """Read-only. A profile is the member's own writing, editable only by them.

    A superadmin needs to be able to SEE one — to answer a report about its content —
    but editing someone's self-description from the platform console would put words in
    their mouth. Removing it is the member's action or a `membership` purge.
    """

    list_display = ("membership", "is_visible", "github_username", "updated_at")
    list_filter = ("is_visible",)
    readonly_fields = tuple(field.name for field in MemberProfile._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD") and super().has_change_permission(request, obj)


@admin.register(MemberProject)
class MemberProjectAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("title", "profile", "position", "updated_at")
    readonly_fields = tuple(field.name for field in MemberProject._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD") and super().has_change_permission(request, obj)
