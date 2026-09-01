from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.makerspaces.models import (
    MakerspaceMembership,
    MakerspaceWaiver,
    MemberProfile,
    MemberProject,
    MembershipRequest,
)
from config.admin_access import SuperuserOnlyModelAdmin


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
