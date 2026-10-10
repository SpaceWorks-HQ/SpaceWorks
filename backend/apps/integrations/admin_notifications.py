from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.integrations.models import NotificationDeliveryLog, NotificationPreference
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """Read-only in /control/; preferences are edited via scoped React settings (Part K)."""

    list_display = ("makerspace", "feature", "channel", "enabled", "updated_at")
    list_filter = ("makerspace", "feature", "channel", "enabled")
    readonly_fields = (
        "makerspace", "feature", "channel", "enabled", "updated_by",
        "created_at", "updated_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NotificationDeliveryLog)
class NotificationDeliveryLogAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """Read-only durable delivery record for non-email channels. Celery owns retry; the one
    superadmin action re-queues rows that exhausted it (the dead-letter path)."""

    list_display = (
        "makerspace", "channel", "feature", "event", "status", "attempts",
        "created_at", "sent_at",
    )
    list_filter = ("makerspace", "channel", "feature", "status")
    actions = ("requeue_failed_deliveries",)

    @admin.action(description="Re-queue failed deliveries", permissions=["view"])
    def requeue_failed_deliveries(self, request, queryset):
        from apps.integrations.delivery_services import retry_delivery
        from apps.integrations.notification_enums import NotificationDeliveryStatus
        from rest_framework.exceptions import APIException
        from apps.backup.not_restored import TenantNotRestored
        from apps.tenant_migration.gate_errors import SourceMigrationGateError

        failed = list(queryset.filter(status=NotificationDeliveryStatus.FAILED))
        count = 0
        for log in failed:
            try:
                updated = retry_delivery(request.user, log, expected_generation=log.retry_generation)
                count += updated.retry_generation > log.retry_generation
            except (APIException, TenantNotRestored, SourceMigrationGateError):
                # A disabled channel, inaccessible tenant or vanished row cannot abort the batch.
                continue
        self.message_user(request, f"Re-queued {count} failed deliver{'y' if count == 1 else 'ies'}.")
    readonly_fields = (
        "makerspace", "channel", "feature", "event", "text_body", "payload",
        "status", "error", "attempts", "created_at", "updated_at", "sent_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
