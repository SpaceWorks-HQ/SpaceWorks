"""Watch availability rises inside the availability transaction; dispatch via F1."""

from django.db import transaction
from django.db.models import CharField, Value
from django.db.models.functions import Cast, Concat
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.audit.services import record
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.makerspaces.platform import feature_enabled
from apps.operations.reminder_types import ReminderMessage, ReminderSource, ReminderSubject
from apps.operations.reminder_consumer_queries import unfinished
from apps.presence.guard import require_active_member, MemberPresenceRequired, WaiverAcceptanceRequired
from .models_watch import InventoryWatch


def tenant_watches(space):
    return rbac.scope_verified_tenant(InventoryWatch.objects.all(), space)


@transaction.atomic
def subscribe(product, user):
    require_active_member(user, product.makerspace)
    if not feature_enabled(product.makerspace, "inventory.notify_when_back"):
        raise ValidationError({"detail": "Notify-me is disabled."})
    # Same lock as quantity writes: a return cannot slip between eligibility and watch.
    product = rbac.scope_public_catalogue(
        type(product).objects.select_for_update(), product.makerspace,
    ).get(pk=product.pk, is_public=True, is_archived=False)
    watch, created = tenant_watches(product.makerspace).get_or_create(
        product=product, user=user, defaults={"makerspace": product.makerspace},
    )
    watch = tenant_watches(product.makerspace).select_for_update().get(pk=watch.pk)
    if not created and (watch.notified_at is not None or watch.ready_at is not None):
        watch.notified_at = watch.ready_at = None
        watch.created_at = timezone.now()
        watch.save(update_fields=["notified_at", "ready_at", "created_at"])
    record(user, "inventory.watch_subscribed", makerspace=product.makerspace, target=product)
    return watch


@transaction.atomic
def unsubscribe(product, user):
    require_active_member(user, product.makerspace)
    tenant_watches(product.makerspace).filter(product=product, user=user).delete()
    record(user, "inventory.watch_unsubscribed", makerspace=product.makerspace, target=product)


def availability_rose(product, previous):
    if product.available_quantity <= 0:
        tenant_watches(product.makerspace).filter(product=product, notified_at__isnull=True).update(ready_at=None)
        return
    if (product.available_quantity <= previous or product.available_quantity <= 0
            or not product.is_public or product.is_archived
            or not feature_enabled(product.makerspace, "inventory.notify_when_back")):
        return
    # Latch only the first rise. No count or borrower identity enters the notification.
    tenant_watches(product.makerspace).filter(product=product, ready_at__isnull=True,
                                  notified_at__isnull=True).update(ready_at=timezone.now())


def watches(space):
    return rbac.scope_for_scheduled_work(
        InventoryWatch.objects.select_related("user", "product", "makerspace"),
        makerspace_id=space.pk,
    ).filter(ready_at__isnull=False, notified_at__isnull=True,
             product__is_public=True, product__is_archived=False, product__available_quantity__gt=0)


def discover(space, now, limit, local_tz):
    rows = unfinished(watches(space), space, "inventory.back_available", "available",
                      Concat(Cast("pk", CharField()), Value(":"), Cast("ready_at", CharField())))
    for row in rows.order_by("ready_at", "pk")[:limit]:
        yield ReminderSubject(row.reminder_subject, "available", row.ready_at)


def current(space, reminder, *, lock=False):
    pk, ready = reminder.subject.split(":", 1)
    rows = watches(space)
    if lock:
        rows = rows.select_for_update(of=("self",))
    return rows.filter(pk=pk, ready_at=ready).first()


def build(space, reminder, now, local_tz):
    row = current(space, reminder)
    if row is None or row.ready_at != reminder.due_at:
        return None
    try:
        require_active_member(row.user, space)
    except (MemberPresenceRequired, WaiverAcceptanceRequired):
        return None
    return ReminderMessage(row.product.name, "available", "An item you follow is available again.")


@transaction.atomic
def dispatch(space, reminder, message, now, local_tz):
    row = current(space, reminder, lock=True)
    if row is None:
        return None

    def payload():
        space.refresh_from_db()
        row.user.refresh_from_db()
        row.product.refresh_from_db()
        try:
            membership = require_active_member(row.user, space).membership
        except (MemberPresenceRequired, WaiverAcceptanceRequired):
            return LifecyclePayload(text="", staff_channels_enabled=False)
        if (not feature_enabled(space, "inventory.notify_when_back")
                or not space.public_inventory_enabled or not row.product.is_public
                or row.product.is_archived or row.product.available_quantity <= 0
                or not membership.receives_notifications
                or not tenant_watches(space).filter(pk=row.pk, created_at=row.created_at,
                                                      notified_at=now).exists()):
            return LifecyclePayload(text="", staff_channels_enabled=False)
        return LifecyclePayload(
            text=message.body, staff_channels_enabled=False,
            emails=(EmailDelivery(to_email=row.user.email, subject=message.title,
                                  text_body=message.body, html_body="", stream="hardware", mute_event="back_available",
                                  audience="requester", user_id=row.user_id),),
        )
    row.notified_at = now
    row.save(update_fields=["notified_at"])
    result = notify_lifecycle(space, feature="hardware_requests", event="back_available", build=payload)
    record(None, "inventory.watch_notified", makerspace=space, target=row.product)
    return result


SOURCE = ReminderSource("inventory.back_available", "public_inventory", discover, build,
                        "inventory.notify_when_back", dispatch)
