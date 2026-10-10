import json
from pathlib import Path
from types import SimpleNamespace

from django.utils import timezone

from apps.integrations.notification_catalog import FEATURE_EVENTS
from apps.integrations.webhook_schema import canonical_event, schema_catalog, structured_body
from apps.integrations.webhooks import webhook_event_body


def log(version=2):
    return SimpleNamespace(pk=42, makerspace_id=1, feature="hardware_requests", event="accepted",
        destination=SimpleNamespace(payload_version=version), text_body="Staff text with member contact",
        created_at=timezone.now(), payload={"request_id": 7, "email": "member@example.test",
        "secret": "must not travel", "occurred_at": "2026-10-11T00:00:00+00:00"})


def test_v2_has_stable_names_and_identifiers_without_template_or_secret_fields():
    row = log()
    body = webhook_event_body(row)
    assert body == {"version": 2, "id": "42", "event": "hardware_requests.accepted", "makerspace_id": 1,
                    "occurred_at": "2026-10-11T00:00:00+00:00", "data": {"request_id": 7}}
    row.text_body = "Changed by a staff template editor"
    assert webhook_event_body(row) == body
    assert canonical_event(row) == "hardware_requests.accepted"


def test_existing_destinations_keep_the_legacy_envelope():
    row = log(version=1)
    body = webhook_event_body(row)
    assert body["event"] == "accepted" and body["text"] == row.text_body
    assert body["structured"]["version"] == 1
    assert "version" not in body


def test_every_matrix_event_has_a_schema_and_catalogue_matches_the_documented_snapshot():
    catalogue = schema_catalog()
    expected = {f"{family}.{event}" for family, events in FEATURE_EVENTS.items() for event in events}
    assert expected <= catalogue["$defs"].keys()
    assert catalogue["$defs"]["hardware_requests.accepted"]["properties"]["event"] == {"const": "hardware_requests.accepted"}
    path = Path(__file__).resolve().parents[2] / "docs" / "webhooks-v2.schema.json"
    assert json.loads(path.read_text()) == catalogue
    for definition in catalogue["$defs"].values():
        assert definition["additionalProperties"] is False
        assert definition["properties"]["data"]["additionalProperties"] is False


def test_v2_refuses_bool_foreign_family_fields_and_uses_snapshot_time_on_retries():
    row = log()
    row.payload.update(request_id=True, booking_id=3, payment_id=4)
    assert structured_body(row)["data"] == {"payment_id": 4}
    first = structured_body(row)["occurred_at"]
    row.created_at = timezone.now()
    assert structured_body(row)["occurred_at"] == first


def test_destination_edit_without_new_field_preserves_opted_in_v2_and_create_defaults_v1():
    from apps.admin_api.serializers_notification_destinations import NotificationDestinationWriteSerializer
    existing = SimpleNamespace(channel="webhook", payload_version=2, webhook_url="stored", signing_secret="stored")
    serializer = NotificationDestinationWriteSerializer(data={"channel": "webhook", "label": "Renamed"},
                                                         context={"instance": existing})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["payload_version"] == 2
    new = NotificationDestinationWriteSerializer(data={"channel": "telegram", "label": "Room", "telegram_chat_id": "123"})
    assert new.is_valid(), new.errors
    assert new.validated_data["payload_version"] == 1
