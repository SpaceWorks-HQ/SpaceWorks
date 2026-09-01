import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.integrations.email_templates_registry import REGISTRY, get_entry
from apps.integrations.models import EmailTemplate
from apps.makerspaces.models import Makerspace, MakerspaceMembership

pytestmark = pytest.mark.django_db


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_user(username, **kwargs):
    return get_user_model().objects.create_user(
        username=username,
        email=kwargs.pop("email", f"{username}@example.com"),
        access_status=kwargs.pop("access_status", User.AccessStatus.ACTIVE),
        **kwargs,
    )


def make_member(username, makerspace, role):
    user = make_user(username)
    MakerspaceMembership.objects.create(user=user, makerspace=makerspace, role=role)
    return user


def make_superadmin(username="email-api-superadmin"):
    return make_user(username, role=User.Role.SUPERADMIN)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def list_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/email-templates"


def detail_url(makerspace, stream, audience, key):
    return (
        f"/api/v1/admin/makerspace/{makerspace.id}/email-templates/"
        f"{stream}/{audience}/{key}"
    )


def reset_url(makerspace, stream, audience, key):
    return f"{detail_url(makerspace, stream, audience, key)}/reset"


def preview_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/email-templates/preview"


def full_payload(stream="hardware"):
    if stream == "printing":
        return {
            "subject": "Custom print {{ print_request.id }}",
            "text_body": "Print title {{ print_request.title }}",
            "html_body": "<p>{{ makerspace.name }}</p>",
            "is_active": True,
        }
    return {
        "subject": "Custom hardware {{ request.id }}",
        "text_body": "Hardware user {{ request.requester_username }}",
        "html_body": "<p>{{ makerspace.name }}</p>",
        "is_active": True,
    }


def streams(response):
    return {row["stream"] for row in response.data}


def test_inventory_manager_sees_only_hardware_and_cannot_touch_printing():
    makerspace = make_space("email-api-inventory")
    manager = make_member(
        "email-api-inventory-manager",
        makerspace,
        MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    client = client_for(manager)

    listed = client.get(list_url(makerspace))
    assert listed.status_code == 200
    assert streams(listed) == {"hardware"}

    printing_url = detail_url(makerspace, "printing", "requester", "submitted")
    assert client.get(printing_url).status_code == 404
    assert client.patch(printing_url, full_payload("printing"), format="json").status_code == 404
    assert client.post(
        preview_url(makerspace),
        {
            "stream": "printing",
            "audience": "requester",
            "key": "submitted",
            **full_payload("printing"),
        },
        format="json",
    ).status_code == 404

    hardware_url = detail_url(makerspace, "hardware", "requester", "request_received")
    detail = client.get(hardware_url)
    assert detail.status_code == 200
    assert detail.data["stream"] == "hardware"

    patched = client.patch(hardware_url, full_payload(), format="json")
    assert patched.status_code == 200
    assert patched.data["is_overridden"] is True
    assert patched.data["subject"] == "Custom hardware {{ request.id }}"


def test_print_manager_sees_only_printing_and_cannot_touch_hardware():
    makerspace = make_space("email-api-printing")
    manager = make_member(
        "email-api-print-manager",
        makerspace,
        MakerspaceMembership.Role.PRINT_MANAGER,
    )
    client = client_for(manager)

    listed = client.get(list_url(makerspace))
    assert listed.status_code == 200
    assert streams(listed) == {"printing"}

    hardware_url = detail_url(makerspace, "hardware", "requester", "request_received")
    assert client.get(hardware_url).status_code == 404
    assert client.patch(hardware_url, full_payload(), format="json").status_code == 404


def test_space_manager_and_superadmin_see_both_streams_and_can_patch():
    makerspace = make_space("email-api-space-manager")
    space_manager = make_member(
        "email-api-space-manager",
        makerspace,
        MakerspaceMembership.Role.SPACE_MANAGER,
    )
    superadmin = make_superadmin()

    for actor, suffix in ((space_manager, "space"), (superadmin, "super")):
        client = client_for(actor)
        listed = client.get(list_url(makerspace))
        assert listed.status_code == 200
        # A space manager holds every stream's action, so they see all six. The narrower
        # roles below are what pin the per-stream scoping.
        assert streams(listed) == {
            "hardware",
            "printing",
            "events",
            "bookings",
            "maintenance",
            "membership",
        }

        hardware = client.patch(
            detail_url(makerspace, "hardware", "requester", "request_received"),
            {**full_payload(), "subject": f"Hardware {suffix}"},
            format="json",
        )
        printing = client.patch(
            detail_url(makerspace, "printing", "requester", "submitted"),
            {**full_payload("printing"), "subject": f"Printing {suffix}"},
            format="json",
        )
        assert hardware.status_code == 200
        assert printing.status_code == 200


def test_out_of_scope_tenant_returns_404_not_403():
    own_space = make_space("email-api-own")
    other_space = make_space("email-api-other")
    manager = make_member(
        "email-api-own-manager",
        own_space,
        MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    client = client_for(manager)
    hardware_url = detail_url(other_space, "hardware", "requester", "request_received")

    assert client.get(list_url(other_space)).status_code == 404
    assert client.get(hardware_url).status_code == 404
    assert client.patch(hardware_url, full_payload(), format="json").status_code == 404


def test_patch_validation_override_get_and_reset():
    makerspace = make_space("email-api-update-reset")
    manager = make_member(
        "email-api-update-reset-manager",
        makerspace,
        MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    client = client_for(manager)
    url = detail_url(makerspace, "hardware", "requester", "request_received")

    broken = client.patch(
        url,
        {**full_payload(), "text_body": "{{ broken syntax %}"},
        format="json",
    )
    assert broken.status_code == 400

    patched = client.patch(url, full_payload(), format="json")
    assert patched.status_code == 200
    assert patched.data["is_overridden"] is True

    detail = client.get(url)
    assert detail.status_code == 200
    assert detail.data["is_overridden"] is True
    assert detail.data["text_body"] == full_payload()["text_body"]

    reset = client.post(reset_url(makerspace, "hardware", "requester", "request_received"))
    default = get_entry("hardware", "requester", "request_received")
    assert reset.status_code == 200
    assert reset.data["is_overridden"] is False
    assert reset.data["subject"] == default.default_subject
    assert EmailTemplate.objects.filter(makerspace=makerspace).count() == 0


def test_preview_renders_draft_without_persisting():
    makerspace = make_space("email-api-preview")
    manager = make_member(
        "email-api-preview-manager",
        makerspace,
        MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    client = client_for(manager)

    response = client.post(
        preview_url(makerspace),
        {
            "stream": "hardware",
            "audience": "requester",
            "key": "request_received",
            "subject": "Preview {{ request.id }}",
            "text_body": "Hello {{ request.requester_username }}",
            "html_body": "<p>{{ makerspace.name }}</p>",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data == {
        "subject": "Preview 42",
        "text_body": "Hello alex",
        "html_body": "<p>TinkerSpace</p>",
    }
    assert EmailTemplate.objects.count() == 0


def test_preview_invalid_syntax_returns_400_not_500():
    makerspace = make_space("email-api-preview-bad")
    manager = make_member(
        "email-api-preview-bad-manager",
        makerspace,
        MakerspaceMembership.Role.INVENTORY_MANAGER,
    )

    response = client_for(manager).post(
        preview_url(makerspace),
        {
            "stream": "hardware",
            "audience": "requester",
            "key": "request_received",
            "subject": "Broken {{ request.id",
            "text_body": "Hello",
            "html_body": "",
        },
        format="json",
    )

    assert response.status_code == 400


def test_list_order_matches_stream_audience_key_sort():
    makerspace = make_space("email-api-ordering")
    manager = make_member(
        "email-api-ordering-manager",
        makerspace,
        MakerspaceMembership.Role.SPACE_MANAGER,
    )

    response = client_for(manager).get(list_url(makerspace))
    keys = [(row["stream"], row["audience"], row["key"]) for row in response.data]

    assert response.status_code == 200
    assert keys == sorted(keys)
    assert set(keys) == set(REGISTRY)
