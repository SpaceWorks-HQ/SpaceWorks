import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.integrations import notification_catalog
from apps.integrations.models import (
    EmailNotificationMute,
    NotificationChannel,
    NotificationFeature,
    NotificationPreference,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership

pytestmark = pytest.mark.django_db
Role = MakerspaceMembership.Role


def make_space(slug, **kwargs):
    return Makerspace.objects.create(name=slug, slug=slug, **kwargs)


def make_user(username, **kwargs):
    return get_user_model().objects.create_user(
        username=username,
        email=kwargs.pop("email", f"{username}@example.com"),
        access_status=kwargs.pop("access_status", User.AccessStatus.ACTIVE),
        **kwargs,
    )


def make_member(username, makerspace, role=Role.SPACE_MANAGER):
    user = make_user(username, role=User.Role.SPACE_MANAGER)
    MakerspaceMembership.objects.create(user=user, makerspace=makerspace, role=role)
    return user


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def rules_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/notification-rules"


def test_manager_gets_catalog_and_empty_mutes():
    makerspace = make_space("rules-catalog")
    manager = make_member("rules-catalog-mgr", makerspace)

    response = authenticated_client(manager).get(rules_url(makerspace))

    assert response.status_code == 200
    catalog = response.data["catalog"]
    assert len(catalog) == 4
    assert response.data["mutes"] == []
    assert response.data["channels"] == [
        {"key": channel.value, "label": channel.label}
        for channel in NotificationChannel
    ]
    assert response.data["features"] == [
        {
            "key": feature.value,
            "label": feature.label,
            "events": list(notification_catalog.FEATURE_EVENTS[feature]),
        }
        for feature in NotificationFeature
    ]
    expected_cells = [
        (feature.value, channel.value)
        for feature in NotificationFeature
        for channel in NotificationChannel
    ]
    # Derived, not a literal: the cell count is features x channels and both grow.
    assert len(response.data["preferences"]) == len(expected_cells)
    assert [
        (cell["feature"], cell["channel"])
        for cell in response.data["preferences"]
    ] == expected_cells
    assert all(cell["source"] == "default" for cell in response.data["preferences"])
    assert all("return_reminder" not in entry["events"] for entry in catalog)
    hw_req = next(
        e for e in catalog if e["stream"] == "hardware" and e["audience"] == "requester"
    )
    assert hw_req["targets"] == ["requester"]
    assert "request_accepted" in hw_req["events"]
    hw_staff = next(
        e for e in catalog if e["stream"] == "hardware" and e["audience"] == "staff"
    )
    assert set(hw_staff["targets"]) == {
        Role.SPACE_MANAGER.value,
        Role.INVENTORY_MANAGER.value,
    }


def test_patch_mutes_then_unmutes_a_staff_role_and_audits():
    makerspace = make_space("rules-toggle")
    manager = make_member("rules-toggle-mgr", makerspace)
    client = authenticated_client(manager)

    mute = {
        "target": Role.INVENTORY_MANAGER.value,
        "stream": "hardware",
        "event": "accepted",
        "audience": "staff",
        "muted": True,
    }
    response = client.patch(rules_url(makerspace), {"changes": [mute]}, format="json")
    assert response.status_code == 200
    assert {
        "target": Role.INVENTORY_MANAGER.value,
        "stream": "hardware",
        "event": "accepted",
        "audience": "staff",
    } in response.data["mutes"]
    assert EmailNotificationMute.objects.filter(makerspace=makerspace).count() == 1
    assert AuditLog.objects.filter(action="email.notification_rules_updated").count() == 1

    response = client.patch(
        rules_url(makerspace), {"changes": [{**mute, "muted": False}]}, format="json"
    )
    assert response.status_code == 200
    assert response.data["mutes"] == []
    assert EmailNotificationMute.objects.filter(makerspace=makerspace).count() == 0


def test_patch_can_mute_requester_audience():
    makerspace = make_space("rules-requester")
    manager = make_member("rules-requester-mgr", makerspace)

    response = authenticated_client(manager).patch(
        rules_url(makerspace),
        {
            "changes": [
                {
                    "target": "requester",
                    "stream": "printing",
                    "event": "completed",
                    "audience": "requester",
                    "muted": True,
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    assert EmailNotificationMute.objects.filter(
        makerspace=makerspace, target="requester", audience="requester"
    ).exists()


def test_patch_rejects_return_reminder_and_applies_nothing():
    makerspace = make_space("rules-reminder")
    manager = make_member("rules-reminder-mgr", makerspace)

    response = authenticated_client(manager).patch(
        rules_url(makerspace),
        {
            "changes": [
                {
                    "target": Role.SPACE_MANAGER.value,
                    "stream": "hardware",
                    "event": "return_reminder",
                    "audience": "staff",
                    "muted": True,
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 400
    assert EmailNotificationMute.objects.filter(makerspace=makerspace).count() == 0


def test_patch_rejects_audience_target_mismatch():
    makerspace = make_space("rules-mismatch")
    manager = make_member("rules-mismatch-mgr", makerspace)

    response = authenticated_client(manager).patch(
        rules_url(makerspace),
        {
            "changes": [
                {
                    "target": Role.SPACE_MANAGER.value,
                    "stream": "hardware",
                    "event": "accepted",
                    "audience": "requester",
                    "muted": True,
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 400
    assert EmailNotificationMute.objects.filter(makerspace=makerspace).count() == 0


def test_patch_invalid_change_in_batch_applies_nothing():
    makerspace = make_space("rules-atomic")
    manager = make_member("rules-atomic-mgr", makerspace)

    response = authenticated_client(manager).patch(
        rules_url(makerspace),
        {
            "changes": [
                {
                    "target": Role.INVENTORY_MANAGER.value,
                    "stream": "hardware",
                    "event": "accepted",
                    "audience": "staff",
                    "muted": True,
                },
                {
                    "target": "requester",
                    "stream": "hardware",
                    "event": "return_reminder",
                    "audience": "requester",
                    "muted": True,
                },
            ]
        },
        format="json",
    )

    assert response.status_code == 400
    # The whole batch is rejected — the first (valid) change must NOT persist.
    assert EmailNotificationMute.objects.filter(makerspace=makerspace).count() == 0


def test_rules_api_returns_404_for_cross_tenant_hidden_and_archived():
    own_space = make_space("rules-own-404")
    other_space = make_space("rules-other-404")
    hidden_space = make_space("rules-hidden-404", superadmin_access_enabled=False)
    archived_space = make_space("rules-archived-404", archived_at=timezone.now())
    manager = make_member("rules-own-mgr-404", own_space)
    superadmin = make_user(
        "rules-superadmin-404",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )

    manager_client = authenticated_client(manager)
    assert manager_client.get(rules_url(other_space)).status_code == 404
    assert manager_client.get(rules_url(archived_space)).status_code == 404
    assert authenticated_client(superadmin).get(rules_url(hidden_space)).status_code == 404


def test_patch_preferences_upserts_last_duplicate_and_audits_safe_meta():
    makerspace = make_space("rules-preferences")
    manager = make_member("rules-preferences-mgr", makerspace)
    payload = {
        "preferences": [
            {"feature": "events", "channel": "slack", "enabled": True},
            {"feature": "printing", "channel": "email", "enabled": False},
            {"feature": "events", "channel": "slack", "enabled": False},
        ]
    }

    response = authenticated_client(manager).patch(
        rules_url(makerspace), payload, format="json"
    )

    assert response.status_code == 200
    rows = NotificationPreference.objects.filter(makerspace=makerspace)
    assert rows.count() == 2
    assert rows.get(feature="events", channel="slack").enabled is False
    cells = {(c["feature"], c["channel"]): c for c in response.data["preferences"]}
    assert cells[("events", "slack")] == {
        "feature": "events", "channel": "slack", "enabled": False, "source": "override"
    }
    assert cells[("hardware_requests", "email")]["source"] == "default"
    log = AuditLog.objects.get(action="notification.preferences_updated")
    assert log.meta == {"preferences": [
        {"feature": "events", "channel": "slack", "enabled": False},
        {"feature": "printing", "channel": "email", "enabled": False},
    ]}
    assert "updated_by" not in str(log.meta)


@pytest.mark.parametrize("payload", [
    {}, {"changes": []}, {"preferences": []},
    {"preferences": [{"feature": "unknown", "channel": "email", "enabled": True}]},
    {"preferences": [{"feature": "events", "channel": "unknown", "enabled": True}]},
    {"preferences": [{"feature": "events", "channel": "email", "enabled": "yes"}]},
    {"changes": [{"target": "requester", "stream": "hardware", "event": "return_reminder", "audience": "requester", "muted": True}]},
    {"preferences": [{"feature": "events", "channel": "email", "enabled": True}], "changes": [{"target": "requester", "stream": "hardware", "event": "return_reminder", "audience": "requester", "muted": True}]},
])
def test_patch_invalid_or_empty_batch_is_atomic(payload):
    makerspace = make_space("rules-invalid")
    manager = make_member("rules-invalid-mgr", makerspace)
    response = authenticated_client(manager).patch(rules_url(makerspace), payload, format="json")
    assert response.status_code == 400
    assert not NotificationPreference.objects.filter(makerspace=makerspace).exists()
    assert not EmailNotificationMute.objects.filter(makerspace=makerspace).exists()
