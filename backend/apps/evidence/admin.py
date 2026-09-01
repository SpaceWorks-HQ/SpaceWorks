from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from apps.evidence.models import EvidenceObjectRetentionState, EvidencePhoto
from apps.evidence.storage import object_exists, presigned_get_url, staging_key
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(EvidencePhoto)
class EvidencePhotoAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "id",
        "makerspace",
        "evidence_type",
        "thumb",
        "object_key",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("evidence_type", "makerspace", "created_at")
    search_fields = (
        "object_key",
        "uploaded_by__username",
        "uploaded_by__email",
        "makerspace__name",
        "makerspace__slug",
    )
    readonly_fields = (
        "makerspace",
        "evidence_type",
        "object_key",
        "photo_preview",
        "uploaded_by",
        "created_at",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("object_retention_state")

    @staticmethod
    def _expired_label(obj):
        state = getattr(obj, "object_retention_state", None)
        if state is None or state.status != EvidenceObjectRetentionState.Status.EXPIRED:
            return None
        return f"Expired at {state.object_expired_at:%Y-%m-%d %H:%M:%S %Z}"

    def photo_preview(self, obj):
        if not obj or not getattr(obj, "object_key", ""):
            return "(no image)"
        if expired := self._expired_label(obj):
            return expired
        try:
            # Same staging fallback as the API read path: evidence that has been
            # uploaded but not yet promoted by a workflow still lives in staging.
            # The list-view thumb deliberately skips this — one HEAD per row is a
            # worse trade than a missing thumbnail on an unconsumed upload.
            key = obj.object_key
            if not object_exists(key) and object_exists(staging_key(key)):
                key = staging_key(key)
            url = presigned_get_url(key)
        except Exception:
            return "(image unavailable)"
        if not url:
            return "(image unavailable)"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener"><img src="{}" '
            'style="max-height:320px;border:1px solid #ccc"/></a><br>'
            '<a href="{}" target="_blank" rel="noopener">Open full image</a>',
            url,
            url,
            url,
        )

    photo_preview.short_description = "Photo"

    def thumb(self, obj):
        if not obj or not getattr(obj, "object_key", ""):
            return "—"
        if self._expired_label(obj):
            return "Expired"
        try:
            url = presigned_get_url(obj.object_key)
        except Exception:
            return "—"
        if not url:
            return "—"
        return format_html('<img src="{}" style="max-height:48px"/>', url)

    thumb.short_description = "Preview"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj)
