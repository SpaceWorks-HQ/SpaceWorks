import pytest
from django.urls import reverse
from drf_spectacular.generators import SchemaGenerator

from apps.audit.models import AuditLog
from tests.events.checkin_helpers import client_for, make_space, make_staff

pytestmark = pytest.mark.django_db


def test_staff_updates_reminder_policy_and_records_field_names_only():
    space = make_space("reminder-policy")
    client = client_for(make_staff(space))
    url = reverse("admin-makerspace", kwargs={"pk": space.pk})
    response = client.patch(url, {"event_reminder_lead_hours": [24, 2],
                                  "booking_reminder_lead_hours": []}, format="json")
    assert response.status_code == 200
    space.refresh_from_db()
    assert space.event_reminder_lead_hours == [24, 2]
    assert space.booking_reminder_lead_hours == []
    audit = AuditLog.objects.get(makerspace=space, action="makerspace.updated")
    assert audit.meta["fields"] == ["booking_reminder_lead_hours", "event_reminder_lead_hours"]


@pytest.mark.parametrize("value", [[0], [-1], [24, 24], [True], [1.5], [8761], "24"])
def test_settings_reject_invalid_reminder_lead_hours(value):
    space = make_space("invalid-reminder-policy")
    response = client_for(make_staff(space)).patch(
        reverse("admin-makerspace", kwargs={"pk": space.pk}),
        {"event_reminder_lead_hours": value}, format="json",
    )
    assert response.status_code == 400
    space.refresh_from_db()
    assert space.event_reminder_lead_hours == [24]


def test_reminder_policy_settings_are_scoped_to_the_staff_makerspace():
    mine, other = make_space("own-reminder-policy"), make_space("other-reminder-policy")
    response = client_for(make_staff(mine)).patch(
        reverse("admin-makerspace", kwargs={"pk": other.pk}),
        {"booking_reminder_lead_hours": []}, format="json",
    )
    assert response.status_code in (403, 404)
    other.refresh_from_db()
    assert other.booking_reminder_lead_hours == [24]


def test_reminder_settings_have_explicit_openapi_array_schemas():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    properties = schema["components"]["schemas"]["Makerspace"]["properties"]
    for field in ("event_reminder_lead_hours", "booking_reminder_lead_hours"):
        assert properties[field]["type"] == "array"
        assert properties[field]["items"]["type"] == "integer"
