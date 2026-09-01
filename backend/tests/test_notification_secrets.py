import json
import socket

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces import origin_scope
from apps.makerspaces.models import Makerspace, MakerspaceMembership

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def public_webhook_dns(monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.webhook_validation.socket.getaddrinfo",
        lambda _host, port, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", port),
            )
        ],
    )


SLACK_URL = "https://hooks.example.com/services/secret-slack"
MATTERMOST_URL = "https://chat.example.com/hooks/secret-mattermost"


def make_space(slug, **kwargs):
    return Makerspace.objects.create(name=slug, slug=slug, **kwargs)


def make_user(username, **kwargs):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.com",
        access_status=kwargs.pop("access_status", User.AccessStatus.ACTIVE),
        **kwargs,
    )


def make_member(username, makerspace, role=MakerspaceMembership.Role.SPACE_MANAGER, **kwargs):
    user = make_user(username, role=User.Role.SPACE_MANAGER, **kwargs)
    MakerspaceMembership.objects.create(user=user, makerspace=makerspace, role=role)
    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def api_settings_url(makerspace):
    return reverse("admin-api-settings", kwargs={"makerspace_id": makerspace.id})


def assert_webhooks_hidden(data, forbidden):
    if isinstance(data, dict):
        assert "slack_webhook_url" not in data
        assert "mattermost_webhook_url" not in data
        for key in ("slack_webhook_url_set", "mattermost_webhook_url_set"):
            if key in data:
                assert type(data[key]) is bool
        for value in data.values():
            assert_webhooks_hidden(value, forbidden)
    elif isinstance(data, list):
        for value in data:
            assert_webhooks_hidden(value, forbidden)
    elif isinstance(data, str):
        assert all(secret not in data for secret in forbidden)


def test_webhooks_are_write_only_across_settings_and_makerspace_responses():
    makerspace = make_space("webhook-leaks")
    manager = make_member("webhook-leaks-manager", makerspace)
    makerspace.set_slack_webhook_url(SLACK_URL)
    makerspace.set_mattermost_webhook_url(MATTERMOST_URL)
    makerspace.save(update_fields=["slack_webhook_url", "mattermost_webhook_url"])
    ciphertexts = (makerspace.slack_webhook_url, makerspace.mattermost_webhook_url)
    client = client_for(manager)

    responses = [
        client.get(api_settings_url(makerspace)),
        client.get(reverse("admin-makerspaces")),
        client.get(reverse("admin-makerspace", kwargs={"pk": makerspace.id})),
    ]
    assert all(response.status_code == 200 for response in responses)
    for response in responses:
        assert_webhooks_hidden(response.data, (SLACK_URL, MATTERMOST_URL, *ciphertexts))
    assert responses[0].data["slack_webhook_url_set"] is True
    assert responses[0].data["mattermost_webhook_url_set"] is True

    superadmin = make_user(
        "webhook-create-superadmin",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )
    created = client_for(superadmin).post(
        reverse("admin-makerspaces"),
        {
            "name": "Webhook Created",
            "slug": "webhook-created",
            "slack_webhook_url": SLACK_URL,
            "mattermost_webhook_url": MATTERMOST_URL,
        },
        format="json",
    )
    assert created.status_code == 201
    assert_webhooks_hidden(created.data, (SLACK_URL, MATTERMOST_URL))


def test_api_settings_webhook_omission_preserves_and_blank_clears_without_audit_leak():
    makerspace = make_space("webhook-patch")
    manager = make_member("webhook-patch-manager", makerspace)
    makerspace.set_slack_webhook_url(SLACK_URL)
    makerspace.set_mattermost_webhook_url(MATTERMOST_URL)
    makerspace.save(update_fields=["slack_webhook_url", "mattermost_webhook_url"])
    client = client_for(manager)

    response = client.patch(api_settings_url(makerspace), {"default_loan_days": 8}, format="json")
    assert response.status_code == 200
    makerspace.refresh_from_db()
    assert makerspace.get_slack_webhook_url() == SLACK_URL
    assert makerspace.get_mattermost_webhook_url() == MATTERMOST_URL

    response = client.patch(
        api_settings_url(makerspace),
        {"slack_webhook_url": "", "mattermost_webhook_url": ""},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["slack_webhook_url_set"] is False
    assert response.data["mattermost_webhook_url_set"] is False
    makerspace.refresh_from_db()
    assert makerspace.get_slack_webhook_url() == ""
    assert makerspace.get_mattermost_webhook_url() == ""
    assert all(
        secret not in json.dumps(log.meta)
        for log in AuditLog.objects.filter(action="api_integration.updated")
        for secret in (SLACK_URL, MATTERMOST_URL)
    )


@pytest.mark.parametrize("invalid", [
    "not-a-url",
    "http://hooks.example.com/services/plain",
    "https://user:pass@hooks.example.com/services/credentialed",
    "https://hooks.example.com/services/fragment#secret",
])
def test_api_settings_rejects_invalid_webhook_without_replacing_prior_value(invalid):
    makerspace = make_space("webhook-invalid")
    manager = make_member("webhook-invalid-manager", makerspace)
    makerspace.set_slack_webhook_url(SLACK_URL)
    makerspace.save(update_fields=["slack_webhook_url"])

    response = client_for(manager).patch(
        api_settings_url(makerspace), {"slack_webhook_url": invalid}, format="json"
    )

    assert response.status_code == 400
    makerspace.refresh_from_db()
    assert makerspace.get_slack_webhook_url() == SLACK_URL


@pytest.mark.parametrize("route_name", [
    "admin-api-settings",
    "admin-notification-recipients",
    "admin-notification-rules",
])
def test_registered_makerspace_routes_enforce_branded_origin_scope(route_name):
    assert origin_scope._MAKERSPACE_KWARG_ROUTES[route_name] == "makerspace_id"
    origin_space = make_space(
        f"origin-{route_name}",
        frontend_domain=f"{route_name}.example.com",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )
    target = make_space(
        f"target-{route_name}",
        frontend_domain=f"target-{route_name}.example.com",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )
    manager = make_member(f"manager-{route_name}", target)
    url = reverse(route_name, kwargs={"makerspace_id": target.id})
    client = client_for(manager)

    assert client.get(url, HTTP_ORIGIN=f"https://{target.frontend_domain}").status_code == 200
    assert client.get(url, HTTP_ORIGIN=f"https://{origin_space.frontend_domain}").status_code == 403


def test_notification_rules_rbac_for_managers_superadmins_and_denied_staff():
    makerspace = make_space("rules-rbac-complete")
    manager = make_member("rules-rbac-manager", makerspace)
    inventory_manager = make_member(
        "rules-rbac-inventory", makerspace, MakerspaceMembership.Role.INVENTORY_MANAGER
    )
    suspended = make_member(
        "rules-rbac-suspended", makerspace, access_status=User.AccessStatus.SUSPENDED
    )
    superadmin = make_user(
        "rules-rbac-superadmin", role=User.Role.SUPERADMIN, is_staff=True, is_superuser=True
    )
    archived = make_space("rules-rbac-archived", archived_at=timezone.now())
    archived_manager = make_member("rules-rbac-archived-manager", archived)
    url = reverse("admin-notification-rules", kwargs={"makerspace_id": makerspace.id})

    assert client_for(manager).get(url).status_code == 200
    assert client_for(superadmin).get(url).status_code == 200
    assert client_for(inventory_manager).get(url).status_code == 404
    assert client_for(suspended).get(url).status_code == 403
    archived_url = reverse("admin-notification-rules", kwargs={"makerspace_id": archived.id})
    assert client_for(archived_manager).get(archived_url).status_code == 404
