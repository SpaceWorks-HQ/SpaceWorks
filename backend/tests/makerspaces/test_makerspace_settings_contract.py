"""The staff makerspace settings routes: what they accept, refuse, and record.

Covers the gaps the 2026-10-09 makerspace audit found in the settings envelope:
a derived field that was writable, a console toggle the API never carried, audit rows
that did not say what changed, and two routes that broke the 404-before-403 contract
or ignored servability.
"""

import json

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.return_helpers import authenticated_client, make_member

pytestmark = pytest.mark.django_db

BOT_TOKEN = "123456:secret-bot-token-value"


def space(slug, **values):
    return Makerspace.objects.create(name=slug, slug=slug, **values)


def inventory_manager(username, makerspace):
    return make_member(
        username,
        makerspace,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )


def detail(makerspace):
    return f"/api/v1/admin/makerspaces/{makerspace.id}"


def api_settings(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/api-settings"


def return_policy(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/return-policy"


# --- cors_allowed_origins is derived, never written by a settings PATCH ---------------


@pytest.mark.parametrize(
    "value", [["https://attacker.example"], "*", [{"origin": "https://x.example"}]]
)
def test_settings_patch_cannot_write_the_public_origin_allowlist(value):
    lab = space("contract-cors", cors_allowed_origins=["https://client.example"])
    manager = make_member("contract-cors-manager", lab)

    response = authenticated_client(manager).patch(
        detail(lab), {"cors_allowed_origins": value, "location": "Bench 4"}, format="json"
    )

    assert response.status_code == 200
    lab.refresh_from_db()
    assert lab.location == "Bench 4"
    assert lab.cors_allowed_origins == ["https://client.example"]
    # Still readable: the console's API-clients summary shows the derived list.
    assert response.data["cors_allowed_origins"] == ["https://client.example"]


# --- lapsed_members_cannot_borrow reaches the console ---------------------------------


def test_lapsed_members_flag_is_read_and_written_by_a_space_manager():
    lab = space("contract-lapsed")
    manager = make_member("contract-lapsed-manager", lab)
    client = authenticated_client(manager)

    assert client.get(detail(lab)).data["lapsed_members_cannot_borrow"] is False

    response = client.patch(detail(lab), {"lapsed_members_cannot_borrow": True}, format="json")

    assert response.status_code == 200
    assert response.data["lapsed_members_cannot_borrow"] is True
    lab.refresh_from_db()
    assert lab.lapsed_members_cannot_borrow is True
    row = AuditLog.objects.filter(action="makerspace.updated", makerspace=lab).latest("id")
    assert row.meta == {"fields": ["lapsed_members_cannot_borrow"]}


def test_staff_without_manage_makerspace_cannot_set_the_lapsed_flag():
    lab = space("contract-lapsed-staff")
    staff = inventory_manager("contract-lapsed-staff-user", lab)

    response = authenticated_client(staff).patch(
        detail(lab), {"lapsed_members_cannot_borrow": True}, format="json"
    )

    assert response.status_code == 404
    lab.refresh_from_db()
    assert lab.lapsed_members_cannot_borrow is False


# --- audit rows name what changed, never secret values ---------------------------------


def test_settings_audit_names_changed_fields_and_never_carries_secret_values():
    lab = space("contract-audit")
    manager = make_member("contract-audit-manager", lab)

    response = authenticated_client(manager).patch(
        detail(lab),
        {
            "public_stats_enabled": True,
            "default_loan_days": lab.default_loan_days,  # sent but unchanged
            "telegram_bot_token": BOT_TOKEN,
            "public_display_name": "Contract Lab",
        },
        format="json",
    )

    assert response.status_code == 200
    row = AuditLog.objects.filter(action="makerspace.updated", makerspace=lab).latest("id")
    assert row.meta == {
        "fields": ["branding_config", "public_stats_enabled", "telegram_bot_token"]
    }
    assert BOT_TOKEN not in json.dumps(row.meta)


def test_an_unchanged_settings_patch_records_no_fields():
    lab = space("contract-noop")
    manager = make_member("contract-noop-manager", lab)

    response = authenticated_client(manager).patch(
        detail(lab), {"location": lab.location}, format="json"
    )

    assert response.status_code == 200
    row = AuditLog.objects.filter(action="makerspace.updated", makerspace=lab).latest("id")
    assert row.meta == {"fields": []}


# --- api-settings: 404 before 403, servable only ---------------------------------------


def test_api_settings_answers_404_before_403_and_audits_field_names():
    lab = space("contract-api")
    other = space("contract-api-other")
    manager = make_member("contract-api-manager", lab)
    foreign_manager = make_member("contract-api-foreign", other)
    staff = inventory_manager("contract-api-staff", lab)

    assert authenticated_client(foreign_manager).get(api_settings(lab)).status_code == 404
    assert authenticated_client(staff).get(api_settings(lab)).status_code == 403
    response = authenticated_client(manager).patch(
        api_settings(lab), {"default_loan_days": 9}, format="json"
    )
    assert response.status_code == 200
    row = AuditLog.objects.filter(action="api_integration.updated", makerspace=lab).latest("id")
    assert row.meta == {"fields": ["default_loan_days"]}


@pytest.mark.parametrize(
    "state",
    [{"archived_at": "now"}, {"lifecycle_state": Makerspace.LifecycleState.IMPORTING}],
)
@pytest.mark.parametrize("route", [api_settings, return_policy])
def test_settings_side_routes_hide_an_unservable_makerspace(state, route):
    lab = space("contract-unservable")
    manager = make_member("contract-unservable-manager", lab)
    values = {key: (timezone.now() if value == "now" else value) for key, value in state.items()}
    Makerspace.objects.filter(pk=lab.pk).update(**values)
    client = authenticated_client(manager)

    assert client.get(route(lab)).status_code == 404
    assert client.patch(route(lab), {"default_loan_days": 3}, format="json").status_code == 404
    assert Makerspace.objects.get(pk=lab.pk).default_loan_days != 3


def test_return_policy_hides_another_makerspace():
    lab = space("contract-return")
    other = space("contract-return-other")
    foreign_manager = make_member("contract-return-foreign", other)

    assert authenticated_client(foreign_manager).get(return_policy(lab)).status_code == 404
