"""Staff API for recipients, destinations and the new template streams (N5).

Console parity is the reason these exist: `/control/` is not proxied on the public
frontend port, so a space manager who cannot reach these endpoints cannot configure
notifications at all. The assertions worth reading twice are the ones about credentials —
a webhook URL is a bearer secret and must never come back out of the API.
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.integrations.models_destinations import NotificationDestination
from apps.integrations.models_recipients import NotificationRecipient
from apps.machines.models import Machine, MachineType
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.roles import ensure_default_roles

pytestmark = pytest.mark.django_db


def make_space(slug):
    space = Makerspace.objects.create(name=slug, slug=slug)
    ensure_default_roles(space)
    return space


def make_user(username, space, role_slug="space_manager", legacy=None):
    user = get_user_model().objects.create_user(
        username=username,
        email=f"{username}@e.com",
        password="test-pass-123",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=space,
        role=legacy or MakerspaceMembership.Role.SPACE_MANAGER,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug=role_slug),
    )
    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def destinations_url(space):
    return f"/api/v1/admin/makerspace/{space.pk}/notification-destinations"


def rules_url(space):
    return f"/api/v1/admin/makerspace/{space.pk}/notification-recipient-rules"


# --- destinations --------------------------------------------------------------------


def test_a_manager_can_create_a_room_and_the_credential_never_comes_back():
    space = make_space("api-dest-create")
    client = client_for(make_user("api-dest-manager", space))

    response = client.post(
        destinations_url(space),
        {
            "channel": "discord",
            "label": "Workshop",
            "webhook_url": "https://hooks.example/super-secret",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["credential_set"] is True
    body = str(response.data)
    assert "super-secret" not in body
    assert "webhook_url" not in response.data

    listed = client.get(destinations_url(space))
    assert "super-secret" not in str(listed.data)


def test_a_blank_webhook_on_update_keeps_the_stored_credential():
    space = make_space("api-dest-keep")
    client = client_for(make_user("api-dest-keep-manager", space))
    created = client.post(
        destinations_url(space),
        {"channel": "slack", "label": "General", "webhook_url": "https://hooks.example/a"},
        format="json",
    ).data

    response = client.put(
        f"{destinations_url(space)}/{created['id']}",
        {"channel": "slack", "label": "Renamed"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["label"] == "Renamed"
    # The caller cannot read the credential back, so requiring it to rename a room would
    # force a re-entry the operator may not be able to perform.
    row = NotificationDestination.objects.get(pk=created["id"])
    assert row.get_webhook_url() == "https://hooks.example/a"


def test_a_telegram_room_needs_a_chat_id_and_refuses_a_webhook():
    space = make_space("api-dest-telegram")
    client = client_for(make_user("api-dest-telegram-manager", space))

    missing = client.post(
        destinations_url(space), {"channel": "telegram", "label": "Front desk"}, format="json"
    )
    assert missing.status_code == 400

    wrong = client.post(
        destinations_url(space),
        {"channel": "telegram", "label": "Front desk", "webhook_url": "https://x"},
        format="json",
    )
    assert wrong.status_code == 400

    ok = client.post(
        destinations_url(space),
        {"channel": "telegram", "label": "Front desk", "telegram_chat_id": "-100222"},
        format="json",
    )
    assert ok.status_code == 201


def test_a_rooms_channel_cannot_be_changed():
    space = make_space("api-dest-channel-lock")
    client = client_for(make_user("api-dest-channel-manager", space))
    created = client.post(
        destinations_url(space),
        {"channel": "slack", "label": "General", "webhook_url": "https://hooks.example/a"},
        format="json",
    ).data

    response = client.put(
        f"{destinations_url(space)}/{created['id']}",
        {"channel": "discord", "label": "General", "webhook_url": "https://hooks.example/b"},
        format="json",
    )

    assert response.status_code == 400


def test_scope_saves_replace_and_reject_foreign_ids():
    space = make_space("api-dest-scope")
    other = make_space("api-dest-scope-other")
    machine_type = MachineType.objects.create(
        makerspace=space, name="Laser", slug="api-dest-laser"
    )
    laser = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Laser")
    foreign_type = MachineType.objects.create(
        makerspace=other, name="Foreign", slug="api-dest-foreign"
    )
    client = client_for(make_user("api-dest-scope-manager", space))
    created = client.post(
        destinations_url(space),
        {
            "channel": "slack",
            "label": "Laser room",
            "webhook_url": "https://hooks.example/a",
            "scope": {"machine_ids": [laser.pk]},
        },
        format="json",
    ).data
    assert created["scope"]["machine_ids"] == [laser.pk]

    foreign = client.put(
        f"{destinations_url(space)}/{created['id']}",
        {
            "channel": "slack",
            "label": "Laser room",
            "scope": {"machine_type_ids": [foreign_type.pk]},
        },
        format="json",
    )
    # A silent drop would leave the operator believing the room is scoped when it is not.
    assert foreign.status_code == 400
    assert foreign.data["unknown"] == [foreign_type.pk]

    replaced = client.put(
        f"{destinations_url(space)}/{created['id']}",
        {"channel": "slack", "label": "Laser room", "scope": {}},
        format="json",
    )
    # Replace, not merge — otherwise unticking the last link is impossible.
    assert replaced.data["scope"]["machine_ids"] == []


def test_a_room_cannot_be_created_for_an_uninstalled_channel():
    space = make_space("api-dest-module")
    space.enabled_modules = [key for key in space.enabled_modules if key != "discord"]
    space.save(update_fields=["enabled_modules"])
    client = client_for(make_user("api-dest-module-manager", space))

    response = client.post(
        destinations_url(space),
        {"channel": "discord", "label": "Nope", "webhook_url": "https://hooks.example/a"},
        format="json",
    )

    assert response.status_code == 400


def test_destinations_are_makerspace_scoped():
    space = make_space("api-dest-tenant-a")
    other = make_space("api-dest-tenant-b")
    outsider = make_user("api-dest-outsider", other)

    response = client_for(outsider).get(destinations_url(space))

    assert response.status_code in (403, 404)


def test_deleting_a_room_keeps_its_delivery_history():
    from apps.integrations.models import NotificationDeliveryLog

    space = make_space("api-dest-delete")
    client = client_for(make_user("api-dest-delete-manager", space))
    created = client.post(
        destinations_url(space),
        {"channel": "slack", "label": "Workshop", "webhook_url": "https://hooks.example/a"},
        format="json",
    ).data
    log = NotificationDeliveryLog.objects.create(
        makerspace=space,
        channel="slack",
        destination_id=created["id"],
        destination_label="Workshop",
        feature="maintenance",
        event="logged",
        text_body="x",
    )

    assert client.delete(f"{destinations_url(space)}/{created['id']}").status_code == 204

    log.refresh_from_db()
    assert log.destination_id is None
    assert log.destination_label == "Workshop"


# --- recipient rules ------------------------------------------------------------------


def test_the_picker_offers_roles_members_and_module_filtered_features():
    space = make_space("api-rules-payload")
    manager = make_user("api-rules-manager", space)
    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=["enabled_modules"])

    payload = client_for(manager).get(rules_url(space)).data

    feature_keys = {item["key"] for item in payload["features"]}
    assert "events" not in feature_keys
    assert {"bookings", "maintenance", "members"} <= feature_keys
    assert any(role["slug"] == "space_manager" for role in payload["roles"])
    assert any(member["id"] == manager.pk for member in payload["members"])


def test_saving_a_selection_replaces_it_and_an_empty_list_restores_the_default():
    space = make_space("api-rules-replace")
    manager = make_user("api-rules-replace-manager", space)
    client = client_for(manager)
    role_id = MakerspaceRole.objects.get(makerspace=space, slug="space_manager").pk

    client.put(
        rules_url(space),
        {
            "feature": "bookings",
            "event": "created",
            "rules": [{"kind": "role", "role_id": role_id}],
        },
        format="json",
    )
    assert NotificationRecipient.objects.filter(makerspace=space).count() == 1

    response = client.put(
        rules_url(space),
        {"feature": "bookings", "event": "created", "rules": []},
        format="json",
    )

    assert response.status_code == 200
    # No rows means the action-based default, which is what keeps booking mail flowing.
    assert NotificationRecipient.objects.filter(makerspace=space).count() == 0


def test_a_named_user_without_a_membership_is_refused_at_the_picker():
    space = make_space("api-rules-outsider")
    client = client_for(make_user("api-rules-outsider-manager", space))
    outsider = get_user_model().objects.create_user(
        username="api-rules-outsider-user",
        email="api-rules-outsider-user@e.com",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )

    response = client.put(
        rules_url(space),
        {
            "feature": "events",
            "event": "published",
            "rules": [{"kind": "user", "user_id": outsider.pk}],
        },
        format="json",
    )

    assert response.status_code == 400
    assert "membership" in response.data["detail"].lower()


def test_a_role_from_another_makerspace_is_refused():
    space = make_space("api-rules-foreign-role")
    other = make_space("api-rules-foreign-role-other")
    client = client_for(make_user("api-rules-foreign-manager", space))
    foreign_role = MakerspaceRole.objects.get(makerspace=other, slug="space_manager")

    response = client.put(
        rules_url(space),
        {
            "feature": "events",
            "event": "published",
            "rules": [{"kind": "role", "role_id": foreign_role.pk}],
        },
        format="json",
    )

    assert response.status_code == 400


def test_an_unknown_event_is_refused():
    space = make_space("api-rules-bad-event")
    client = client_for(make_user("api-rules-bad-event-manager", space))

    response = client.put(
        rules_url(space),
        {"feature": "bookings", "event": "not_a_real_event", "rules": []},
        format="json",
    )

    assert response.status_code == 400


def test_a_selection_for_an_uninstalled_module_is_refused():
    space = make_space("api-rules-module")
    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=["enabled_modules"])
    client = client_for(make_user("api-rules-module-manager", space))

    response = client.put(
        rules_url(space),
        {"feature": "events", "event": "published", "rules": []},
        format="json",
    )

    assert response.status_code == 400


def test_recipient_rules_are_makerspace_scoped():
    space = make_space("api-rules-tenant-a")
    other = make_space("api-rules-tenant-b")

    response = client_for(make_user("api-rules-tenant-outsider", other)).get(rules_url(space))

    assert response.status_code in (403, 404)


# --- template streams -----------------------------------------------------------------


def test_the_template_list_now_includes_the_fablab_streams():
    space = make_space("api-tmpl-streams")
    client = client_for(make_user("api-tmpl-manager", space))

    response = client.get(f"/api/v1/admin/makerspace/{space.pk}/email-templates")

    assert response.status_code == 200
    streams = {item["stream"] for item in response.data}
    assert {"events", "bookings", "maintenance", "membership"} <= streams


def test_a_template_stream_for_an_uninstalled_module_is_hidden():
    space = make_space("api-tmpl-module")
    space.enabled_modules = [key for key in space.enabled_modules if key != "bookings"]
    space.save(update_fields=["enabled_modules"])
    client = client_for(make_user("api-tmpl-module-manager", space))

    response = client.get(f"/api/v1/admin/makerspace/{space.pk}/email-templates")

    streams = {item["stream"] for item in response.data}
    assert "bookings" not in streams
    assert "maintenance" in streams


def test_a_maintenance_template_can_be_edited_through_the_api():
    space = make_space("api-tmpl-edit")
    client = client_for(make_user("api-tmpl-edit-manager", space))
    url = (
        f"/api/v1/admin/makerspace/{space.pk}/email-templates/"
        "maintenance/staff/logged"
    )

    response = client.patch(
        url,
        {
            "subject": "Service: {{ machine.name }}",
            "text_body": "{{ machine.name }} was serviced.",
            "html_body": "",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["is_overridden"] is True


def test_an_invalid_template_body_is_refused():
    space = make_space("api-tmpl-invalid")
    client = client_for(make_user("api-tmpl-invalid-manager", space))
    url = f"/api/v1/admin/makerspace/{space.pk}/email-templates/events/staff/published"

    response = client.patch(
        url,
        {
            "subject": "ok",
            "text_body": "{% if event.title %}unclosed",
            "html_body": "",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == 400
