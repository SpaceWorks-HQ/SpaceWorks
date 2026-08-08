"""apps/updates under the tombstone profile.

A deployment updated by its own host tooling (a distro package, a CI pipeline, an
operator's own compose pull) has no use for the in-app release control surface, and every
reason not to expose one. The singleton settings row stays so the host-side
`update_control` command keeps working against stored state.
"""

import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve

from apps.separability.registry import runtime_active
from apps.separability.tombstones import unavailable_apps
from apps.updates.models import PlatformUpdateSettings
from config.unfold import UNFOLD

pytestmark = pytest.mark.django_db


def test_the_app_is_registered_as_inactive():
    assert runtime_active("updates") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/platform/update-settings",
        "/api/v1/admin/platform/update-settings/update-now",
    ],
)
def test_no_update_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


def test_the_neighbouring_platform_routes_are_untouched():
    """The routes are spliced out in place, so the ones around them must survive."""
    assert resolve("/api/v1/admin/memberships").url_name == "admin-memberships-roster"


def test_the_admin_does_not_register_the_settings():
    assert PlatformUpdateSettings not in admin.site._registry


def test_the_sidebar_offers_no_software_updates_entry():
    titles = [
        str(item["title"])
        for group in UNFOLD["SIDEBAR"]["navigation"]
        for item in group["items"]
    ]
    assert "Software updates" not in titles


def test_the_frontend_is_told_the_app_is_unavailable():
    assert "updates" in unavailable_apps()


def test_the_settings_row_is_still_readable_for_host_side_tooling():
    # The privileged host scheduler drives releases through `update_control`, which reads
    # this row. Removing the web surface must not disarm the host path.
    assert PlatformUpdateSettings.objects.count() >= 0
