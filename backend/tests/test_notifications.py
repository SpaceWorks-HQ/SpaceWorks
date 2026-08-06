import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership
from apps.notifications.models import Notification
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def list_url(makerspace):
    return f"/api/v1/notifications/makerspace/{makerspace.id}"


def count_url(makerspace):
    return f"/api/v1/notifications/makerspace/{makerspace.id}/unread-count"


def read_url(makerspace, notification):
    return f"/api/v1/notifications/makerspace/{makerspace.id}/{notification.id}/read"


def read_all_url(makerspace):
    return f"/api/v1/notifications/makerspace/{makerspace.id}/read-all"


def enable_notifications(makerspace):
    makerspace.enabled_modules = list(makerspace.enabled_modules) + ["notifications"]
    makerspace.save(update_fields=["enabled_modules"])


def make_guest(username, makerspace):
    return make_member(
        username,
        makerspace,
        membership_role=MakerspaceMembership.Role.GUEST_ADMIN,
        role=User.Role.GUEST_ADMIN,
    )


def make_print_manager(username, makerspace):
    return make_member(
        username,
        makerspace,
        membership_role=MakerspaceMembership.Role.PRINT_MANAGER,
        role=User.Role.REQUESTER,
    )


def test_notifications_module_disabled_returns_400():
    makerspace = make_space("notif-module-off")
    # `notifications` is a registered, installable module now, so the disabled path has
    # to be set up explicitly rather than inherited from the default.
    makerspace.enabled_modules = [
        key for key in makerspace.enabled_modules if key != "notifications"
    ]
    makerspace.save(update_fields=["enabled_modules"])
    manager = make_member("notif-module-off-manager", makerspace)

    response = authenticated_client(manager).get(list_url(makerspace))

    assert response.status_code == 400
    assert "module" in response.data


def test_notifications_reject_non_member_guest_and_archived_makerspace():
    makerspace = make_space("notif-access")
    archived = make_space("notif-archived")
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    enable_notifications(makerspace)
    enable_notifications(archived)
    guest = make_guest("notif-access-guest", makerspace)
    non_member = make_user("notif-access-non-member", access_status=User.AccessStatus.ACTIVE)
    archived_manager = make_member("notif-archived-manager", archived)

    assert authenticated_client(non_member).get(list_url(makerspace)).status_code == 404
    assert authenticated_client(guest).get(list_url(makerspace)).status_code == 403
    assert authenticated_client(archived_manager).get(list_url(archived)).status_code == 404


def test_list_is_tenant_scoped_and_unread_filter_and_count_work():
    makerspace = make_space("notif-list")
    other = make_space("notif-list-other")
    enable_notifications(makerspace)
    enable_notifications(other)
    manager = make_member("notif-list-manager", makerspace)
    read = Notification.objects.create(
        makerspace=makerspace,
        level=Notification.Level.INFO,
        event="request.accepted",
        title="Already read",
        read_at=timezone.now(),
    )
    unread = Notification.objects.create(
        makerspace=makerspace,
        level=Notification.Level.CRITICAL,
        event="request.submitted",
        title="Needs attention",
        body="A requester is waiting.",
        url_path="/admin/requests",
    )
    Notification.objects.create(makerspace=other, title="Other makerspace")

    client = authenticated_client(manager)
    listed = client.get(list_url(makerspace))
    unread_only = client.get(f"{list_url(makerspace)}?unread=true")
    count = client.get(count_url(makerspace))

    assert listed.status_code == 200
    assert listed.data["count"] == 2
    assert {row["id"] for row in listed.data["results"]} == {read.id, unread.id}
    assert unread_only.status_code == 200
    assert [row["id"] for row in unread_only.data["results"]] == [unread.id]
    assert count.status_code == 200
    assert count.data == {"count": 1}


def test_print_manager_can_read_notifications_when_module_is_enabled():
    makerspace = make_space("notif-print-manager")
    enable_notifications(makerspace)
    manager = make_print_manager("notif-print-manager-user", makerspace)
    Notification.objects.create(makerspace=makerspace, title="Printer alert")

    response = authenticated_client(manager).get(list_url(makerspace))

    assert response.status_code == 200
    assert response.data["count"] == 1


def test_mark_read_is_idempotent_and_cross_tenant_notification_is_not_markable():
    makerspace = make_space("notif-read")
    other = make_space("notif-read-other")
    enable_notifications(makerspace)
    enable_notifications(other)
    manager = make_member("notif-read-manager", makerspace)
    notification = Notification.objects.create(makerspace=makerspace, title="Unread")
    other_notification = Notification.objects.create(makerspace=other, title="Other")
    client = authenticated_client(manager)

    first = client.post(read_url(makerspace, notification), format="json")
    notification.refresh_from_db()
    first_read_at = notification.read_at
    second = client.post(read_url(makerspace, notification), format="json")
    notification.refresh_from_db()
    cross_tenant = client.post(read_url(makerspace, other_notification), format="json")

    assert first.status_code == 200
    assert first.data["read_at"] is not None
    assert second.status_code == 200
    assert notification.read_at == first_read_at
    assert cross_tenant.status_code == 404


def test_mark_all_read_marks_only_own_unread_notifications():
    makerspace = make_space("notif-read-all")
    other = make_space("notif-read-all-other")
    enable_notifications(makerspace)
    enable_notifications(other)
    manager = make_member("notif-read-all-manager", makerspace)
    own_a = Notification.objects.create(makerspace=makerspace, title="One")
    own_b = Notification.objects.create(makerspace=makerspace, title="Two")
    already_read = Notification.objects.create(
        makerspace=makerspace,
        title="Three",
        read_at=timezone.now(),
    )
    other_notification = Notification.objects.create(makerspace=other, title="Other")

    response = authenticated_client(manager).post(read_all_url(makerspace), format="json")
    own_a.refresh_from_db()
    own_b.refresh_from_db()
    already_read.refresh_from_db()
    other_notification.refresh_from_db()

    assert response.status_code == 200
    assert response.data == {"updated": 2}
    assert own_a.read_at is not None
    assert own_b.read_at is not None
    assert already_read.read_at is not None
    assert other_notification.read_at is None