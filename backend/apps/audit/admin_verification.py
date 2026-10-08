"""Read-only /control/ views of staff audit verification runs.

Superadmins inspect runs here, including the closed failure code and the two diagnostic
coordinates staff responses omit. There is deliberately no "run verification" action:
the scoped asynchronous API is the only way to start one.
"""

from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.audit.models import AuditVerificationRun, AuditVerificationRunEvent
from config.admin_access import SuperuserOnlyModelAdmin

EVENT_FIELDS = (
    "state", "attempt", "row_count", "mac_valid_count", "unattested_count",
    "mac_invalid_count", "mac_unavailable_count", "unbatched_count",
    "local_batch_verified_count", "batch_invalid_count", "batch_unavailable_count",
    "externally_anchored_count", "chain_status", "anchor_status", "failure_code",
    "first_audit_log_id", "first_batch_seq", "created_at",
)


class _ReadOnly:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AuditVerificationRunEventInline(_ReadOnly, TabularInline):
    model = AuditVerificationRunEvent
    fields = EVENT_FIELDS
    readonly_fields = EVENT_FIELDS
    extra = 0
    can_delete = False


@admin.register(AuditVerificationRun)
class AuditVerificationRunAdmin(_ReadOnly, SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("pk", "makerspace", "requested_by", "snapshot_max_id", "created_at")
    list_filter = ("makerspace", "created_at")
    readonly_fields = (
        "makerspace", "requested_by", "action_filter", "target_type_filter",
        "target_id_filter", "actor_filter", "start_at", "end_at", "snapshot_max_id",
        "filter_fingerprint", "created_at",
    )
    inlines = (AuditVerificationRunEventInline,)


@admin.register(AuditVerificationRunEvent)
class AuditVerificationRunEventAdmin(_ReadOnly, SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("run", "state", "attempt", "chain_status", "anchor_status", "failure_code")
    list_filter = ("state", "failure_code")
    readonly_fields = ("run", *EVENT_FIELDS)
