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
        from apps.audit import services as audit
        from apps.integrations.dispatch_channels import _enqueue_notification
        from apps.integrations.notification_enums import NotificationDeliveryStatus

        failed = list(queryset.filter(status=NotificationDeliveryStatus.FAILED))
        for log in failed:
            log.status = NotificationDeliveryStatus.PENDING
            log.error = ""
            log.save(update_fields=["status", "error", "updated_at"])
            audit.record(
                request.user,
                "notification.delivery_requeued",
                makerspace=log.makerspace,
                target=log,
                meta={"channel": log.channel, "event": log.event, "attempts": log.attempts},
            )
            _enqueue_notification(log.pk)
        self.message_user(request, f"Re-queued {len(failed)} failed deliver{'y' if len(failed) == 1 else 'ies'}.")
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
