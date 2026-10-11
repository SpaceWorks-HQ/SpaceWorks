from types import SimpleNamespace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.inventory.models import InventoryProduct
from apps.operations.models import StocktakeSession, StocktakePolicy, StocktakeSchedule
from apps.operations.services_stocktake_workflow import create_stocktake, add_stocktake_line, complete_stocktake, approve_stocktake
from apps.operations.serializers_stocktake import StocktakeSerializer, StocktakeLineSerializer
from apps.operations import stocktake_discipline as discipline
from tests.return_helpers import make_space, make_member

pytestmark = pytest.mark.django_db


def world(slug, threshold=None):
    space = make_space(slug)
    space.enabled_features = sorted(set(space.enabled_features) | {"stocktake.discipline"})
    space.save(update_fields=["enabled_features"])
    actor = make_member(slug+"-counter", space)
    approver = make_member(slug+"-approver", space)
    StocktakePolicy.objects.create(makerspace=space, blind_default=True, variance_threshold=threshold)
    item = InventoryProduct.objects.create(makerspace=space, name="Tools", total_quantity=10, available_quantity=10)
    return space, actor, approver, item


def test_blind_nested_and_count_response_hide_expected_and_variance():
    space, actor, _, item = world("stock-blind")
    session = create_stocktake(actor, space, {})
    line = add_stocktake_line(actor, session, {"product_id": item.pk, "counted_quantity": 8})
    assert line.expected_quantity == 10
    assert StocktakeLineSerializer(line).data["expected_quantity"] is None
    assert StocktakeSerializer(session).data["lines"][0]["variance_quantity"] is None
    session = complete_stocktake(actor, session)
    assert StocktakeSerializer(session).data["lines"][0]["expected_quantity"] == 10


def test_large_variance_needs_different_approver_and_low_variance_autoapproves():
    space, actor, approver, item = world("stock-threshold", 1)
    session = create_stocktake(actor, space, {})
    add_stocktake_line(actor, session, {"product_id": item.pk, "counted_quantity": 7})
    session = complete_stocktake(actor, session)
    assert session.approval_required and session.status == "completed"
    with pytest.raises(ValidationError):
        approve_stocktake(actor, session)
    assert approve_stocktake(approver, session).approved_by_id == approver.pk
    second = create_stocktake(actor, space, {})
    add_stocktake_line(actor, second, {"product_id": item.pk, "counted_quantity": 9})
    second = complete_stocktake(actor, second)
    assert second.status == "approved" and second.approval_required is False


def test_scheduled_count_skips_missed_intervals_and_dispatch_is_idempotent():
    space, _, _, _ = world("stock-scheduled", 1)
    due = timezone.localdate()-timedelta(days=65)
    row = StocktakeSchedule.objects.create(makerspace=space, name="Shelf", interval_days=30, next_due=due, blind=True)
    now = timezone.now()
    subject = next(iter(discipline.discover(space, now, 10, ZoneInfo("UTC"))))
    reminder = SimpleNamespace(subject=subject.subject)
    message = discipline.build(space, reminder, now, ZoneInfo("UTC"))
    discipline.dispatch(space, reminder, message, now, ZoneInfo("UTC"))
    discipline.dispatch(space, reminder, message, now, ZoneInfo("UTC"))
    assert StocktakeSession.objects.filter(makerspace=space).count() == 1
    assert StocktakeSession.objects.get(makerspace=space).blind
    row.refresh_from_db()
    assert row.next_due > timezone.localdate()
    assert (row.next_due-due).days % 30 == 0


def test_legacy_defaults_and_feature_off_remain_approval_only():
    space = make_space("stock-default")
    actor = make_member("stock-default-user", space)
    session = create_stocktake(actor, space, {})
    assert not session.blind and session.variance_threshold is None
    assert complete_stocktake(actor, session).status == "completed"
    with pytest.raises(ValidationError):
        create_stocktake(actor, space, {"blind": True})


def test_schedule_api_rejects_zero_interval_foreign_container_and_unknown_fields():
    from django.urls import reverse
    from rest_framework.test import APIClient
    from apps.boxes.models import Box
    space, actor, _, _ = world("stock-schedule-api")
    other = make_space("stock-schedule-api-other")
    foreign = Box.objects.create(makerspace=other, label="Private", code="foreign")
    client = APIClient()
    client.force_authenticate(actor)
    url = reverse("stocktake-schedules", kwargs={"makerspace_id": space.pk})
    payload = {"name": "Monthly", "interval_days": 30, "next_due": str(timezone.localdate())}
    assert client.post(url, {**payload, "interval_days": 0}, format="json").status_code == 400
    assert client.post(url, {**payload, "container": foreign.pk}, format="json").status_code == 400
    assert client.post(url, {**payload, "makerspace": other.pk}, format="json").status_code == 400
    assert client.post(url, payload, format="json").status_code == 201
    assert StocktakeSchedule.objects.filter(makerspace=space).count() == 1


def test_count_rejects_foreign_target_and_container_with_validation_errors():
    from apps.boxes.models import Box
    space, actor, _, _ = world("stock-count-boundary")
    other = make_space("stock-count-boundary-other")
    foreign_item = InventoryProduct.objects.create(makerspace=other, name="Private tool")
    foreign_box = Box.objects.create(makerspace=other, label="Private shelf")
    session = create_stocktake(actor, space, {})
    with pytest.raises(ValidationError):
        add_stocktake_line(actor, session, {"product_id": foreign_item.pk, "counted_quantity": 1})
    with pytest.raises(ValidationError):
        add_stocktake_line(actor, session, {"product_id": foreign_item.pk, "container_id": foreign_box.pk, "counted_quantity": 1})
    assert not session.lines.exists()
