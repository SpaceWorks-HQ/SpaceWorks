import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.updates import services
from apps.updates.models import PlatformUpdateSettings
from apps.updates.releases import select_release
from tests.return_helpers import authenticated_client, make_user

pytestmark = pytest.mark.django_db
OLD = "0.5.0-main.1.aaaaaaaaaaaa"
NEW = "0.5.0-main.2.bbbbbbbbbbbb"
BETA = "0.5.1-beta.3.cccccccccccc"


def release(version=NEW, **changes):
    return {
        "tag_name": f"v{version}", "name": "SpaceWorks 0.5.0", "draft": False,
        "prerelease": False, "published_at": "2026-10-10T10:00:00Z",
        "body": "## Fixed\nReturn evidence is protected.",
        "html_url": f"https://github.com/SpaceWorks-HQ/SpaceWorks/releases/tag/v{version}",
        **changes,
    }


def root_client():
    return authenticated_client(make_user("channel-root", role=User.Role.SUPERADMIN, access_status="active"))


def test_stable_is_default_and_filters_drafts_and_prereleases():
    row = PlatformUpdateSettings.load()
    assert row.channel == "stable"
    releases = [
        release(BETA, prerelease=True, published_at="2026-10-11T10:00:00Z"),
        release(NEW, draft=True), release(OLD),
    ]
    assert select_release(releases, row.channel)["version"] == OLD


def test_beta_includes_prereleases_and_stable_releases_in_publication_order():
    beta = release(BETA, prerelease=True, published_at="2026-10-11T10:00:00Z")
    assert select_release([release(), beta], "beta")["version"] == BETA
    # A later stable release is also eligible for operators on beta.
    stable = release(published_at="2026-10-12T10:00:00Z")
    assert select_release([beta, stable], "beta")["version"] == NEW


@pytest.mark.parametrize("changes", [
    {"tag_name": "latest"}, {"tag_name": f"SpaceWorks v{NEW}"}, {"draft": True},
    {"prerelease": "false"}, {"published_at": None}, {"published_at": "not-a-date"},
])
def test_malformed_or_unfinished_releases_are_not_installed(changes):
    with pytest.raises(ValueError):
        select_release([release(**changes)], "stable")


def test_beta_tag_cannot_enter_stable_even_with_a_mislabelled_prerelease_flag():
    with pytest.raises(ValueError):
        select_release([release(BETA)], "stable")


def test_channel_switch_clears_notes_and_version_and_is_audited():
    services.claim_release(current_version=OLD, releases=[release()])
    response = root_client().patch(reverse("admin-platform-update-settings"), {"channel": "beta"}, format="json")
    assert response.status_code == 200
    assert response.data["channel"] == "beta"
    assert response.data["available_version"] == response.data["release_notes"] == response.data["release_url"] == ""
    assert response.data["last_checked_at"] is None
    assert AuditLog.objects.get(action="platform.update_settings_updated").meta == {"channel": "beta"}


@pytest.mark.parametrize("status", ["running", "queued"])
def test_channel_cannot_change_during_an_update(status):
    row = PlatformUpdateSettings.load()
    row.status = status
    row.save()
    response = root_client().patch(reverse("admin-platform-update-settings"), {"channel": "beta"}, format="json")
    assert response.status_code == 400
    assert response.data["reason"] == "update_busy"
    row.refresh_from_db()
    assert row.channel == "stable"
    assert not AuditLog.objects.filter(action="platform.update_settings_updated").exists()


def test_unknown_channel_is_validated_at_the_serializer_boundary():
    response = root_client().patch(reverse("admin-platform-update-settings"), {"channel": "nightly"}, format="json")
    assert response.status_code == 400
    assert PlatformUpdateSettings.load().channel == "stable"


def test_release_notes_are_cached_with_the_exact_version_and_no_display_prefix():
    claimed, version = services.claim_release(current_version=OLD, releases=[release()])
    assert not claimed and version == NEW
    response = root_client().get(reverse("admin-platform-update-settings"))
    assert response.data["release_notes"] == release()["body"]
    assert response.data["available_version"] == NEW
    assert response.data["release_url"] == release()["html_url"]


def test_host_command_selects_and_records_notes_from_json_without_shell_interpolation():
    output = StringIO()
    with patch("sys.stdin", StringIO(json.dumps([release(body="<script>alert(1)</script> $(secret)")]))):
        call_command("update_control", "claim", f"--current={OLD}", "--releases-stdin", "--force", stdout=output)
    assert output.getvalue().strip() == f"run {NEW}"
    row = PlatformUpdateSettings.load()
    assert row.release_notes == "<script>alert(1)</script> $(secret)"
    assert row.running_since is not None


def test_release_note_links_are_restricted_to_the_project_release_page():
    assert select_release([release(html_url="javascript:alert(1)")], "stable")["url"] == ""


def test_control_channel_change_uses_locked_state_and_audits_fields_only():
    from django.contrib.admin import AdminSite
    from apps.updates.admin import PlatformUpdateSettingsAdmin, PlatformUpdateSettingsForm

    row = PlatformUpdateSettings.load()
    row.available_version, row.release_notes = NEW, "Previous channel"
    row.save()
    form = PlatformUpdateSettingsForm(data={"channel": "beta", "automatic_updates_enabled": True}, instance=row)
    assert form.is_valid(), form.errors
    obj = form.save(commit=False)
    actor = make_user("control-channel-root", role=User.Role.SUPERADMIN, access_status="active")
    PlatformUpdateSettingsAdmin(PlatformUpdateSettings, AdminSite()).save_model(
        SimpleNamespace(user=actor), obj, form, True,
    )
    row.refresh_from_db()
    assert row.channel == "beta" and row.available_version == row.release_notes == ""
    assert AuditLog.objects.get(action="platform.update_settings_updated").meta == {
        "via": "control", "created": False,
        "changed_fields": ["automatic_updates_enabled", "channel"],
    }


def test_control_add_keeps_the_singleton_identity_for_django_logging():
    from django.contrib.admin import AdminSite
    from apps.updates.admin import PlatformUpdateSettingsAdmin, PlatformUpdateSettingsForm

    form = PlatformUpdateSettingsForm(data={"channel": "stable", "automatic_updates_enabled": False})
    assert form.is_valid(), form.errors
    obj = form.save(commit=False)
    actor = make_user("control-add-root", role=User.Role.SUPERADMIN, access_status="active")
    PlatformUpdateSettingsAdmin(PlatformUpdateSettings, AdminSite()).save_model(
        SimpleNamespace(user=actor), obj, form, False,
    )
    assert obj.pk == form.instance.pk == 1
    assert PlatformUpdateSettings.objects.count() == 1
