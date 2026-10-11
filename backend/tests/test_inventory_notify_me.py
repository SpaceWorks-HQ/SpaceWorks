from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from apps.inventory import availability, notify_me
from apps.inventory.models import InventoryProduct
from apps.inventory.models_watch import InventoryWatch
from apps.inventory.serializers import PublicProductSerializer
from tests.return_helpers import make_space, make_member

pytestmark = pytest.mark.django_db


def world(slug):
    space = make_space(slug)
    space.enabled_features = sorted(set(space.enabled_features) | {"inventory.notify_when_back"})
    space.save(update_fields=["enabled_features"])
    member = make_member(slug + "-member", space)
    product = InventoryProduct.objects.create(makerspace=space, name="Drill", borrowing_terms="Return clean.")
    return space, member, product


def test_once_per_rise_and_own_address(monkeypatch):
    space, member, product = world("watch-edge")
    watch = notify_me.subscribe(product, member)
    availability.adjust_quantities(product, delta_available=1, delta_damaged=0, delta_lost=0,
                                    reason="restocked", actor=member)
    watch.refresh_from_db()
    first = watch.ready_at
    availability.adjust_quantities(product, delta_available=1, delta_damaged=0, delta_lost=0,
                                    reason="restocked again", actor=member)
    watch.refresh_from_db()
    assert watch.ready_at == first
    sent = []
    monkeypatch.setattr(notify_me, "notify_lifecycle", lambda space, **kw: sent.append(kw["build"]()))
    subject = next(iter(notify_me.discover(space, timezone.now(), 10, ZoneInfo("UTC"))))
    reminder = SimpleNamespace(subject=subject.subject, due_at=subject.due_at)
    message = notify_me.build(space, reminder, timezone.now(), ZoneInfo("UTC"))
    notify_me.dispatch(space, reminder, message, timezone.now(), ZoneInfo("UTC"))
    assert sent[0].emails[0].to_email == member.email
    assert sent[0].staff_channels_enabled is False
    assert not list(notify_me.discover(space, timezone.now(), 10, ZoneInfo("UTC")))
    # Re-subscribing after consumption opens a new occurrence, not a duplicate marker.
    notify_me.subscribe(product, member)
    watch.refresh_from_db()
    assert watch.ready_at is None and watch.notified_at is None


@pytest.mark.parametrize("mode,show", [("hidden", True), ("status_only", True), ("exact_count", False)])
def test_terms_and_notifications_never_reveal_hidden_counts(mode, show, monkeypatch):
    space, member, product = world("watch-"+mode+str(show))
    product.public_availability_mode = mode
    product.show_public_count = show
    product.save()
    notify_me.subscribe(product, member)
    availability.adjust_quantities(product, delta_available=73, delta_damaged=0, delta_lost=0,
                                    reason="restock", actor=member)
    product.refresh_from_db()
    data = PublicProductSerializer(product).data
    assert "count" not in (data["availability"] or {})
    assert "Return clean." in data["borrowing_terms"]
    watch = InventoryWatch.objects.get(product=product)
    reminder = SimpleNamespace(subject=f"{watch.pk}:{watch.ready_at.isoformat()}", due_at=watch.ready_at)
    message = notify_me.build(space, reminder, timezone.now(), ZoneInfo("UTC"))
    assert "73" not in message.body
    assert member.email not in str(data)


def test_contact_injection_cross_tenant_and_feature_off():
    space, member, product = world("watch-api")
    other = make_space("watch-other")
    hidden = InventoryProduct.objects.create(makerspace=other, name="Private")
    client = APIClient()
    client.force_authenticate(member)
    url = reverse("public-inventory-watch", kwargs={"makerspace_slug": space.slug, "pk": product.pk})
    assert client.post(url, {"email": "other@example.com"}, format="json").status_code == 400
    foreign = reverse("public-inventory-watch", kwargs={"makerspace_slug": space.slug, "pk": hidden.pk})
    assert client.post(foreign, {}, format="json").status_code == 404
    space.enabled_features = [key for key in space.enabled_features if key != "inventory.notify_when_back"]
    space.save(update_fields=["enabled_features"])
    assert client.post(url, {}, format="json").status_code == 400


def test_rollback_does_not_latch_watch():
    from django.db import transaction
    space, member, product = world("watch-rollback")
    watch = notify_me.subscribe(product, member)
    with pytest.raises(RuntimeError), transaction.atomic():
        availability.adjust_quantities(product, delta_available=1, delta_damaged=0, delta_lost=0,
                                        reason="test rollback", actor=member)
        raise RuntimeError("rollback")
    watch.refresh_from_db()
    assert watch.ready_at is None


def test_terms_inherit_loan_days_and_only_show_live_deposit_policy():
    from decimal import Decimal
    from apps.payments.models import MakerspacePaymentSettings
    space, _, product = world("terms-deposit")
    space.enabled_features = sorted(set(space.enabled_features) | {"charges.enabled", "charges.loans"})
    space.save(update_fields=["enabled_features"])
    product.makerspace = space
    product.loan_days = 3
    product.deposit_amount = Decimal("12.50")
    product.save()
    MakerspacePaymentSettings.objects.create(makerspace=space, loan_deposit_mode="per_product", default_currency="inr")
    terms = PublicProductSerializer(product).data["borrowing_terms"]
    assert "3 days" in terms and "INR 12.50 per item" in terms
    space.enabled_features.remove("charges.enabled")
    space.save(update_fields=["enabled_features"])
    assert "Deposit:" not in PublicProductSerializer(product).data["borrowing_terms"]


def test_skipped_watch_does_not_starve_later_watch_in_one_slot_batch():
    from uuid import uuid4
    from apps.operations.models_reminders import ReminderSchedule
    from apps.operations.reminder_services import schedule_reminders
    space, member, product = world("watch-fairness")
    first = notify_me.subscribe(product, member)
    availability.adjust_quantities(product, delta_available=1, delta_damaged=0, delta_lost=0,
                                    reason="restock", actor=member)
    subject = next(iter(notify_me.discover(space, timezone.now(), 1, ZoneInfo("UTC"))))
    schedule_reminders(makerspace=space, source=notify_me.SOURCE.key, subject=subject.subject,
                       kind=subject.kind, due_at=subject.due_at)
    member.is_active = False
    member.save(update_fields=["is_active"])
    reminder = SimpleNamespace(subject=subject.subject, due_at=subject.due_at)
    assert notify_me.build(space, reminder, timezone.now(), ZoneInfo("UTC")) is None
    ReminderSchedule.objects.filter(makerspace=space, source=notify_me.SOURCE.key).update(
        state="completed", claim_token=uuid4(), claimed_at=timezone.now(), completed_at=timezone.now(),
    )
    second_member = make_member("watch-fairness-next", space)
    second = notify_me.subscribe(product, second_member)
    availability.adjust_quantities(product, delta_available=1, delta_damaged=0, delta_lost=0,
                                    reason="another restock", actor=second_member)
    found = list(notify_me.discover(space, timezone.now(), 1, ZoneInfo("UTC")))
    assert len(found) == 1 and found[0].subject.startswith(f"{second.pk}:")
    assert not found[0].subject.startswith(f"{first.pk}:")


def test_stock_falling_before_dispatch_cancels_stale_notice_and_rearms():
    space, member, product = world("watch-stale")
    watch = notify_me.subscribe(product, member)
    availability.adjust_quantities(product, delta_available=1, delta_damaged=0, delta_lost=0,
                                    reason="restock", actor=member)
    subject = next(iter(notify_me.discover(space, timezone.now(), 1, ZoneInfo("UTC"))))
    stale = SimpleNamespace(subject=subject.subject, due_at=subject.due_at)
    availability.adjust_quantities(product, delta_available=-1, delta_damaged=0, delta_lost=0,
                                    reason="taken", actor=member)
    watch.refresh_from_db()
    assert watch.ready_at is None
    assert notify_me.build(space, stale, timezone.now(), ZoneInfo("UTC")) is None
    availability.adjust_quantities(product, delta_available=1, delta_damaged=0, delta_lost=0,
                                    reason="returned", actor=member)
    fresh = next(iter(notify_me.discover(space, timezone.now(), 1, ZoneInfo("UTC"))))
    assert fresh.subject != subject.subject
    assert notify_me.build(space, SimpleNamespace(subject=fresh.subject, due_at=fresh.due_at),
                           timezone.now(), ZoneInfo("UTC")) is not None
