"""Atomic user-requested retries; transport remains at-least-once after provider acceptance."""

from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit import services as audit
from apps.integrations.models import EmailLog, NotificationDeliveryLog
from apps.tenant_migration.gate_runtime import tenant_write


def retry_delivery(actor, log, *, expected_generation=None):
    from apps.integrations.dispatch import _enqueue
    from apps.integrations.dispatch_channels import _enqueue_notification
    if not (actor and actor.is_authenticated and actor.is_active and actor.access_status == "active") or not rbac.can(
        actor, rbac.Action.MANAGE_MAKERSPACE, log.makerspace_id,
    ):
        raise PermissionDenied()
    if log.makerspace_id is None:
        raise ValidationError({"makerspace": "Use the platform email controls for platform mail."})
    enqueue = _enqueue if isinstance(log, EmailLog) else _enqueue_notification
    with tenant_write(log.makerspace_id):
        if isinstance(log, EmailLog):
            from apps.encryption.write_fence import assert_mapped_write_allowed
            assert_mapped_write_allowed(log.makerspace_id)
        locked = rbac.scope_by_action(
            actor, rbac.Action.MANAGE_MAKERSPACE, type(log).objects.all(),
        ).select_for_update().filter(pk=log.pk, makerspace_id=log.makerspace_id).first()
        if locked is None:
            raise NotFound("This delivery was removed by retention.")
        if expected_generation is not None and expected_generation != locked.retry_generation:
            return locked
        if locked.status in ("pending", "sending", "sent"):
            return locked
        if locked.status != "failed":
            raise ValidationError({"status": "Only failed deliveries may be retried."})
        from apps.integrations.dispatch import email_module_blocks
        from apps.integrations.dispatch_channels import channel_module_blocks

        blocked = email_module_blocks(locked.makerspace, locked.stream, locked.event) if isinstance(
            locked, EmailLog,
        ) else channel_module_blocks(locked.makerspace, locked.channel)
        if blocked:
            raise ValidationError({"module": "This delivery channel is disabled."})
        if isinstance(log, EmailLog) and not (locked.text_body or locked.html_body):
            raise ValidationError({"detail": "This email has no stored content to retry."})
        locked.status = "pending"
        locked.error = ""
        locked.retry_generation += 1
        locked.save(update_fields=["status", "error", "retry_generation", "updated_at"])
        if isinstance(log, EmailLog):
            audit.record(actor, "email.retried", makerspace=locked.makerspace, target=locked,
                         meta={"email_log_id": locked.pk, "event": locked.event, "stream": locked.stream})
        else:
            audit.record(actor, "notification.delivery_requeued", makerspace=locked.makerspace, target=locked,
                         meta={"channel": locked.channel, "event": locked.event, "attempts": locked.attempts})
        transaction.on_commit(lambda: enqueue(locked.pk), robust=True)
        return locked
