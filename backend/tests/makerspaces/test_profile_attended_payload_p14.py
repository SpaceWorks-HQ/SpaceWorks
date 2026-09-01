"""Phase 1 -- the activity payload contract, the audit, and the directory boundary.

`activity` stopped being a passthrough `JSONField` and became a nested serializer. That is
exactly where a makerspace with the events module off starts emitting nulls for keys which
today are absent entirely: a zero says "attended nothing", an absent key says "this space
does not run events", and those are different statements.

The consent and list-content cases live in `test_profile_attended_events_p14.py`.
"""

import pytest

from apps.audit.models import AuditLog
from apps.makerspaces import profile_services
from tests.makerspaces.attendance_helpers import (
    attend,
    authed,
    directory_url,
    disable_events,
    make_space,
    member,
    profile_url,
    publish,
)

pytestmark = pytest.mark.django_db


# --- the payload contract ----------------------------------------------------------


def test_module_off_omits_every_event_key_including_the_new_one():
    space = disable_events(make_space())
    m = member(space)
    publish(m)

    assert profile_services.profile_activity(m) == {}


def test_serialized_profile_omits_absent_activity_keys_rather_than_nulling_them():
    space = disable_events(make_space())
    m = member(space)
    publish(m)

    response = authed(m.user).get(profile_url(space))

    assert response.status_code == 200
    assert response.data["activity"] == {}
    for key in ("events_attended", "events_registered", "recent_attended_events"):
        assert key not in response.data["activity"]


def test_serialized_profile_exposes_the_flag_and_the_list():
    space = make_space()
    m = member(space)
    attend(m, "Laser night")
    publish(m)

    response = authed(m.user).get(profile_url(space))

    assert response.status_code == 200
    assert response.data["show_attended_events"] is True
    assert response.data["activity"]["events_attended"] == 1
    assert len(response.data["activity"]["recent_attended_events"]) == 1


def test_an_opted_out_profile_serializes_without_the_list_key():
    space = make_space()
    m = member(space)
    attend(m, "Laser night")
    publish(m, attended=False)

    response = authed(m.user).get(profile_url(space))

    assert response.status_code == 200
    assert response.data["show_attended_events"] is False
    assert "recent_attended_events" not in response.data["activity"]
    # The aggregate count is unchanged -- it was already published before this feature.
    assert response.data["activity"]["events_attended"] == 1


def test_the_flag_is_writable_through_the_api():
    space = make_space()
    m = member(space)

    response = authed(m.user).put(
        profile_url(space), {"show_attended_events": True}, format="json"
    )

    assert response.status_code in (200, 202)
    assert profile_services.profile_for(m).show_attended_events is True


# --- audit -------------------------------------------------------------------------


def test_the_consent_change_is_audited_without_any_event_content():
    """The audit log is append-only, so anything written there is undeletable PII."""
    space = make_space()
    m = member(space)
    attend(m, "Sensitive Support Group Meetup")
    publish(m)

    entry = AuditLog.objects.filter(
        action="member.profile_updated", makerspace=space
    ).latest("id")

    assert entry.meta["attended_events_shown"] is True
    assert entry.meta["attended_events_changed"] is True
    assert "Sensitive Support Group Meetup" not in str(entry.meta)


def test_an_unrelated_profile_save_reports_no_consent_change():
    space = make_space()
    m = member(space)
    publish(m)

    profile_services.save_profile(m, {"headline": "Maker"})
    entry = AuditLog.objects.filter(
        action="member.profile_updated", makerspace=space
    ).latest("id")

    assert entry.meta["attended_events_changed"] is False
    assert entry.meta["attended_events_shown"] is True


def test_withdrawing_consent_is_audited_as_a_change():
    space = make_space()
    m = member(space)
    publish(m)

    publish(m, attended=False)
    entry = AuditLog.objects.filter(
        action="member.profile_updated", makerspace=space
    ).latest("id")

    assert entry.meta["attended_events_shown"] is False
    assert entry.meta["attended_events_changed"] is True


# --- the directory must stay minimal ------------------------------------------------


def test_the_directory_listing_carries_no_activity_at_all():
    """The listing is display name, headline and avatar. Attendance is a detail read."""
    space = make_space()
    m = member(space)
    attend(m, "Laser night")
    publish(m)

    response = authed(m.user).get(directory_url(space))

    assert response.status_code == 200
    row = next(r for r in response.data["members"] if r["membership_id"] == m.pk)
    assert set(row) == {"membership_id", "display_name", "headline", "avatar_url"}
