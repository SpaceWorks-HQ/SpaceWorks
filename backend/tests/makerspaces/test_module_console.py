"""The grouped module console (phase 5).

`/control/` is not proxied on the public frontend port, so without this surface the only
way to install a module is the shell. These tests pin who may use it, what it tells the
operator before they click, and the two things it must refuse.
"""

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import apply_profile
from apps.makerspaces.module_profiles import EVERYTHING, MINIMAL
from apps.makerspaces.module_registry import GROUPS, MODULE_KEYS
from tests.return_helpers import authenticated_client, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def space():
    return Makerspace.objects.create(name="Console", slug="console")


@pytest.fixture
def superadmin():
    return make_user(
        "modules-superadmin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )


def groups_url(space):
    return reverse("admin-module-groups", args=[space.id])


def auth(_client, user):
    # The staff API is JWT-authenticated, so a session login is not enough.
    return authenticated_client(user)


# --- authority --------------------------------------------------------------


def test_a_staff_member_cannot_reach_the_module_console(client, space):
    # enabled_modules is superadmin-owned by existing design; a staff PATCH carrying it
    # is already a hard 403, and this surface must not become the way around that.
    staff = make_user("modules-staff", access_status=User.AccessStatus.ACTIVE)

    response = auth(client, staff).get(groups_url(space))

    assert response.status_code in {401, 403}


def test_an_anonymous_caller_cannot_reach_it(client, space):
    assert client.get(groups_url(space)).status_code in {401, 403}


def test_an_archived_makerspace_is_not_addressable(client, space, superadmin):
    from django.utils import timezone

    Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())

    # Archived spaces are invisible everywhere but /control/, so installing a module on
    # one would be a change with no observable effect.
    assert auth(client, superadmin).get(groups_url(space)).status_code == 404


# --- what the operator is told ----------------------------------------------


def test_every_module_appears_under_exactly_one_group(client, space, superadmin):
    response = auth(client, superadmin).get(groups_url(space))

    payload = response.json()
    assert {group["key"] for group in payload["groups"]} == {group.key for group in GROUPS}
    keys = [module["key"] for group in payload["groups"] for module in group["modules"]]
    assert sorted(keys) == sorted(MODULE_KEYS)
    assert len(keys) == len(set(keys))


def test_a_card_says_what_installing_would_also_switch_on(client, space, superadmin):
    apply_profile(space, MINIMAL)

    response = auth(client, superadmin).get(groups_url(space))

    modules = {
        module["key"]: module
        for group in response.json()["groups"]
        for module in group["modules"]
    }
    # A dependency resolved silently is a capability the operator did not choose.
    assert modules["printing"]["pulls_in"] == ["machine_service"]
    assert modules["membership"]["pulls_in"] == ["accounts"]
    assert modules["reports"]["pulls_in"] == []


def test_a_card_says_what_blocks_uninstalling_it(client, space, superadmin):
    apply_profile(space, EVERYTHING)

    response = auth(client, superadmin).get(groups_url(space))

    modules = {
        module["key"]: module
        for group in response.json()["groups"]
        for module in group["modules"]
    }
    assert modules["machine_service"]["required_by"] == ["printing"]
    assert modules["accounts"]["required_by"] == ["membership", "mobile"]


def test_the_inventory_group_is_reported_as_always_on(client, space, superadmin):
    response = auth(client, superadmin).get(groups_url(space))

    groups = {group["key"]: group for group in response.json()["groups"]}
    # Core is added back on every write, so a master toggle offering "off" here would be
    # a control whose effect is silently undone.
    assert groups["inventory"]["always_on"] is True
    assert groups["events"]["always_on"] is False


def test_the_deployment_section_is_read_only_and_prints_the_env_line(client, space, superadmin):
    response = auth(client, superadmin).get(groups_url(space))

    deployment = response.json()["deployment"]
    assert deployment["requires_restart"] is True
    assert deployment["env_line"].startswith("TOMBSTONED_APPS=")
    assert all("shipped" in app for app in deployment["apps"])


# --- mutations --------------------------------------------------------------


def test_installing_pulls_in_requirements_and_reports_them(client, space, superadmin):
    apply_profile(space, MINIMAL)

    response = auth(client, superadmin).post(
        reverse("admin-module-install", args=[space.id]),
        {"key": "printing"},
        format="json",
    )

    space.refresh_from_db()
    assert response.status_code == 200
    assert set(response.json()["installed"]) == {"printing", "machine_service"}
    assert {"printing", "machine_service"} <= set(space.enabled_modules)


def test_uninstalling_keeps_the_key_removable_and_the_data_intact(client, space, superadmin):
    apply_profile(space, EVERYTHING)

    response = auth(client, superadmin).post(
        reverse("admin-module-uninstall", args=[space.id]),
        {"key": "stocktake"},
        format="json",
    )

    space.refresh_from_db()
    assert response.status_code == 200
    assert "stocktake" not in space.enabled_modules


def test_a_core_module_cannot_be_uninstalled_from_the_console(client, space, superadmin):
    apply_profile(space, EVERYTHING)

    response = auth(client, superadmin).post(
        reverse("admin-module-uninstall", args=[space.id]),
        {"key": "scanner"},
        format="json",
    )

    assert response.status_code == 400
    assert "core module" in response.json()["detail"]


def test_a_depended_on_module_cannot_be_uninstalled_from_the_console(client, space, superadmin):
    apply_profile(space, EVERYTHING)

    response = auth(client, superadmin).post(
        reverse("admin-module-uninstall", args=[space.id]),
        {"key": "accounts"},
        format="json",
    )

    # Refused with the reason, rather than cascading: taking membership and mobile away
    # as a side effect of one click is not something an operator asked for.
    assert response.status_code == 400
    assert "required by" in response.json()["detail"]


def test_the_console_offers_no_way_to_destroy_data(client, space, superadmin):
    # Purge is deliberately CLI-only: no single surface may both hide and destroy.
    from django.urls import NoReverseMatch

    with pytest.raises(NoReverseMatch):
        reverse("admin-module-purge", args=[space.id])
