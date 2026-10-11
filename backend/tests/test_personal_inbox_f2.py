from uuid import uuid4

import pytest

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.integrations.models import NotificationPreference
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.notifications.inbox import InboxDelivery
from apps.notifications.models import MemberNotificationPreference, Notification, NotificationInboxRow
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def enable(space):
    space.enabled_features = [*space.enabled_features, "notifications.member_inbox", "notifications.member_preferences"]
    space.save(update_fields=["enabled_features"])


def member(name, space):
    user = make_user(name, role=User.Role.REQUESTER, access_status=User.AccessStatus.ACTIVE)
    MakerspaceMembership.objects.create(
        makerspace=space, user=user, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
    )
    return user


def inbox_row(space, user, **values):
    return NotificationInboxRow.objects.create(makerspace=space, user=user,
        event_key=uuid4(), feature="bookings", event="confirmed", title="Your booking", **values)


def url(space, suffix=""):
    return f"/api/v1/notifications/inbox/{space.pk}{suffix}"


def test_personal_list_count_and_read_are_isolated_from_other_members_and_tenants():
    space, other = make_space("f2-inbox"), make_space("f2-inbox-other")
    enable(space)
    first, second = member("f2-first", space), member("f2-second", space)
    mine, theirs = inbox_row(space, first), inbox_row(space, second)
    inbox_row(other, first)
    legacy = Notification.objects.create(makerspace=space, title="Shared staff notice")
    client = authenticated_client(first)
    assert [row["id"] for row in client.get(url(space)).data["results"]] == [mine.pk]
    assert client.get(url(space, "/unread-count")).data == {"count": 1}
    assert client.post(url(space, f"/{theirs.pk}/read")).status_code == 404
    assert client.post(url(space, f"/{mine.pk}/read")).status_code == 200
    theirs.refresh_from_db()
    legacy.refresh_from_db()
    assert theirs.read_at is None and legacy.read_at is None
    assert AuditLog.objects.filter(actor=first, action="notification.inbox_read").exists()


def test_read_all_changes_only_callers_rows_and_is_idempotent():
    space = make_space("f2-read-all")
    enable(space)
    first, second = member("f2-read-first", space), member("f2-read-second", space)
    inbox_row(space, first)
    other = inbox_row(space, second)
    client = authenticated_client(first)
    assert client.post(url(space, "/read-all")).data == {"updated": 1}
    assert client.post(url(space, "/read-all")).data == {"updated": 0}
    other.refresh_from_db()
    assert other.read_at is None


def test_module_and_member_feature_off_return_400_and_restricted_user_is_refused():
    space = make_space("f2-off")
    user = member("f2-off-user", space)
    inbox_row(space, user)
    client = authenticated_client(user)
    assert client.get(url(space)).status_code == 400
    enable(space)
    space.enabled_modules = [key for key in space.enabled_modules if key != "notifications"]
    space.save(update_fields=["enabled_modules"])
    assert client.get(url(space)).status_code == 400
    user.access_status = User.AccessStatus.SUSPENDED
    user.save(update_fields=["access_status"])
    assert authenticated_client(user).get(url(space)).status_code == 403


def test_staff_and_machine_only_users_read_their_own_rows_without_member_feature():
    space = make_space("f2-machine")
    manager = make_member("f2-machine-manager", space, membership_role=MakerspaceMembership.Role.MACHINE_MANAGER,
                          role=User.Role.REQUESTER)
    row = inbox_row(space, manager)
    assert authenticated_client(manager).get(url(space)).data["results"][0]["id"] == row.pk


def test_account_only_owner_can_read_explicit_rows_but_revoked_members_cannot():
    space = make_space("f2-account-only")
    enable(space)
    owner = make_user("f2-borrower", access_status=User.AccessStatus.ACTIVE)
    inbox_row(space, owner)
    client = authenticated_client(owner)
    assert client.get(url(space)).status_code == 200
    MakerspaceMembership.objects.create(makerspace=space, user=owner, role="member", status="revoked")
    assert client.get(url(space)).status_code == 403


def test_matrix_writes_requester_wording_and_deduplicates_staff_owner(monkeypatch):
    space = make_space("f2-matrix")
    enable(space)
    owner, staff = make_member("f2-owner-staff", space), make_member("f2-other-staff", space)
    from apps.integrations.notification_enums import NotificationChannel
    for channel in NotificationChannel.values:
        NotificationPreference.objects.create(makerspace=space, feature="bookings", channel=channel,
                                              enabled=channel == "in_app")
    payload = LifecyclePayload(text="Staff-only applicant detail", emails=(EmailDelivery(
        to_email=owner.email, user_id=owner.pk, audience="requester", subject="Your booking",
        text_body="Your booking was confirmed", stream="bookings",
    ),), inbox=(InboxDelivery(owner.pk, "Booking", "Own summary"),))
    notify_lifecycle(space, feature="bookings", event="confirmed", build=lambda: payload, sync=True)
    rows = NotificationInboxRow.objects.filter(makerspace=space)
    assert rows.count() == 2
    assert rows.get(user=owner).summary == "Own summary"
    assert rows.get(user=staff).summary == "Staff-only applicant detail"
    assert not Notification.objects.filter(makerspace=space).exists()


def test_preference_update_is_audited_and_cannot_enable_a_tenant_disabled_channel():
    space = make_space("f2-pref-api")
    enable(space)
    user = member("f2-pref-user", space)
    client = authenticated_client(user)
    path = f"/api/v1/notifications/preferences/{space.pk}"
    off = {"feature": "events", "channel": "email", "enabled": False}
    assert client.patch(path, off, format="json").status_code == 200
    assert MemberNotificationPreference.objects.get(user=user).enabled is False
    assert client.patch(path, {**off, "enabled": True}, format="json").status_code == 400
    assert AuditLog.objects.filter(actor=user, action="notification.preference_updated").count() == 1


def test_inbox_opt_out_is_independent_of_email_and_no_email_is_needed():
    space = make_space("f2-no-email")
    enable(space)
    user = member("f2-no-email-member", space)
    user.email = ""
    user.save(update_fields=["email"])
    payload = LifecyclePayload(text="Staff", inbox=(InboxDelivery(user.pk, "Own title", "Own body"),))
    notify_lifecycle(space, feature="events", event="registration_approved", build=lambda: payload, sync=True)
    assert NotificationInboxRow.objects.filter(user=user).count() == 1
    MemberNotificationPreference.objects.create(makerspace=space, user=user, feature="events", channel="in_app", enabled=False)
    notify_lifecycle(space, feature="events", event="registration_approved", build=lambda: payload, sync=True)
    assert NotificationInboxRow.objects.filter(user=user).count() == 1


def test_legacy_only_staff_alerts_have_personal_read_state_without_widening_old_visibility(django_capture_on_commit_callbacks):
    from apps.notifications.emit import emit_notification
    space = make_space("f2-legacy")
    manager = make_member("f2-legacy-manager", space)
    regular = member("f2-legacy-member", space)
    machine = make_member("f2-legacy-machine", space, membership_role=MakerspaceMembership.Role.MACHINE_MANAGER,
                          role=User.Role.REQUESTER)
    with django_capture_on_commit_callbacks(execute=True):
        emit_notification(space, title="Stocktake", event="stocktake.completed", body="Awaiting approval")
    assert Notification.objects.filter(makerspace=space).count() == 1
    assert NotificationInboxRow.objects.filter(user=manager).count() == 1
    assert not NotificationInboxRow.objects.filter(user__in=[regular, machine]).exists()
    assert authenticated_client(manager).post(url(space, "/read-all")).data == {"updated": 1}
    assert Notification.objects.get(makerspace=space).read_at is None
