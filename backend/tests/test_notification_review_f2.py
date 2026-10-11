"""F2 review regressions exercise real fan-out, policy queries and retry locks."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.audit.models import AuditLog
from apps.integrations.delivery_services import retry_delivery
from apps.integrations.email_preferences import address_hash, blocked_reason
from apps.integrations.models import EmailSuppression, NotificationDeliveryLog, NotificationPreference
from apps.integrations.models_recipients import NotificationRecipient
from apps.integrations.notification_catalog import default_state
from apps.integrations.notification_enums import NotificationChannel
from apps.integrations.notify import LifecyclePayload, notify_lifecycle
from apps.makerspaces.models import MakerspaceMembership
from apps.notifications.inbox import InboxDelivery, safe_link
from apps.notifications.models import MemberNotificationPreference, NotificationInboxRow
from tests.return_helpers import make_member, make_space
from tests.test_personal_inbox_f2 import enable, member

pytestmark = pytest.mark.django_db


def inbox_only(space, family):
    for channel in NotificationChannel.values:
        NotificationPreference.objects.create(
            makerspace=space, feature=family, channel=channel, enabled=channel == "in_app",
        )


def test_matrix_requester_selection_and_blanket_opt_out_apply_to_personal_inbox():
    space = make_space("f2-review-selection")
    enable(space)
    inbox_only(space, "events")
    owner, staff = member("f2-review-owner", space), make_member("f2-review-staff", space)
    payload = LifecyclePayload(text="Staff detail", inbox=(InboxDelivery(owner.pk, "Your event", "Own detail"),))
    rule = NotificationRecipient.objects.create(
        makerspace=space, feature="events", event="registration_approved", kind="user", user=staff,
    )
    notify_lifecycle(space, feature="events", event="registration_approved", build=lambda: payload, sync=True)
    assert not NotificationInboxRow.objects.filter(user=owner).exists()
    assert NotificationInboxRow.objects.get(user=staff).summary == "Staff detail"
    rule.delete()
    membership = MakerspaceMembership.objects.get(makerspace=space, user=owner)
    membership.receives_notifications = False
    membership.save(update_fields=["receives_notifications"])
    notify_lifecycle(space, feature="events", event="registration_approved", build=lambda: payload, sync=True)
    assert not NotificationInboxRow.objects.filter(user=owner).exists()
    membership.receives_notifications = True
    membership.save(update_fields=["receives_notifications"])
    notify_lifecycle(space, feature="events", event="registration_approved", build=lambda: payload, sync=True)
    assert NotificationInboxRow.objects.get(user=owner).summary == "Own detail"


@pytest.mark.parametrize("tenant_enabled,override,expected", [
    (False, None, 0), (True, False, 0), (False, True, 1), (True, None, 1),
])
def test_booking_requester_switch_applies_without_an_email_address(tenant_enabled, override, expected):
    from apps.bookings.models import BookableSpace, Booking
    from apps.bookings.notifications import notify_booking_status

    space = make_space("f2-review-booking")
    enable(space)
    inbox_only(space, "bookings")
    space.booking_requester_notifications_enabled = tenant_enabled
    space.save(update_fields=["booking_requester_notifications_enabled"])
    owner = member("f2-review-booker", space)
    target = BookableSpace.objects.create(
        makerspace=space, name="Studio", requester_notifications_enabled=override,
    )
    start = timezone.now() + timedelta(hours=1)
    # Retained legacy bookings can lack contact snapshots. Bulk insert deliberately
    # bypasses today's save boundary, which requires email and phone for NEW rows.
    booking = Booking.objects.bulk_create([Booking(
        space=target, member=owner, name="Booker", email="", phone="",
        starts_at=start, ends_at=start + timedelta(hours=1), status="confirmed",
    )])[0]
    notify_booking_status(booking, "confirmed", sync=True)
    assert NotificationInboxRow.objects.filter(user=owner).count() == expected


def test_event_adapter_respects_requester_selection_for_an_actual_registration():
    from apps.events.models import EventRegistration
    from apps.events.notifications import notify_event_lifecycle
    from tests.events.test_services import make_event

    space = make_space("f2-review-event")
    enable(space)
    inbox_only(space, "events")
    owner, staff = member("f2-review-registrant", space), make_member("f2-review-event-staff", space)
    event = make_event(space)
    registration = EventRegistration.objects.create(
        event=event, member=owner, name="Registrant", email="", phone="",
    )
    NotificationRecipient.objects.create(
        makerspace=space, feature="events", event="registration_approved", kind="user", user=staff,
    )
    notify_event_lifecycle(event, "registration_approved", registration.pk, sync=True)
    assert not NotificationInboxRow.objects.filter(user=owner).exists()
    NotificationRecipient.objects.create(
        makerspace=space, feature="events", event="registration_approved", kind="requester",
    )
    notify_event_lifecycle(event, "registration_approved", registration.pk, sync=True)
    assert "Your registration" in NotificationInboxRow.objects.get(user=owner).summary


@pytest.mark.parametrize("has_email", [False, True])
def test_printing_inbox_is_email_independent_and_omits_public_tokens(has_email):
    from apps.machines.service_printing_emails import notify_printer_service_status
    from tests.test_b7a_kernel_emails import _printer_request

    space, request, owner, _ = _printer_request("f2-review-print")
    enable(space)
    inbox_only(space, "printing")
    owner.access_status = "active"
    if not has_email:
        owner.email = ""
        request.contact_email = ""
        request.save(update_fields=["contact_email"])
    owner.save(update_fields=["access_status", "email"])
    notify_printer_service_status(request, "completed", sync=True)
    row = NotificationInboxRow.objects.get(user=owner)
    assert row.summary == "Your print request: completed."
    assert str(request.public_token) not in row.summary
    assert row.link == f"/m/{space.slug}/member"


def test_api_access_owner_without_email_still_receives_an_inbox_row():
    from apps.apiclients.models import ApiKeyRequest
    from apps.apiclients.notifications import notify_api_key_request_resolved

    space = make_space("f2-review-api")
    enable(space)
    inbox_only(space, "api_access")
    owner = member("f2-review-api-owner", space)
    owner.email = ""
    owner.save(update_fields=["email"])
    request = ApiKeyRequest.objects.create(makerspace=space, requester=owner, label="Automation", status="approved")
    notify_api_key_request_resolved(request, sync=True)
    row = NotificationInboxRow.objects.get(user=owner)
    assert "Automation" in row.summary and "approved" in row.summary


@pytest.mark.parametrize("event", ["request.submitted", "machine_service.completed"])
def test_legacy_direct_alerts_survive_the_planned_matrix_default(event, django_capture_on_commit_callbacks):
    from apps.notifications.emit import emit_notification

    space = make_space("f2-review-direct")
    staff = make_member("f2-review-direct-staff", space)
    assert default_state("hardware_requests", "in_app") is False
    assert default_state("printing", "in_app") is False
    with django_capture_on_commit_callbacks(execute=True):
        emit_notification(space, event=event, title="Direct alert", body="Staff details")
    assert NotificationInboxRow.objects.get(user=staff).summary == "Staff details"


@pytest.mark.parametrize("change", ["module_off", "frozen"])
def test_legacy_on_commit_emitter_rechecks_the_tenant_before_writing(change, django_capture_on_commit_callbacks):
    from apps.notifications.emit import emit_notification
    from apps.notifications.models import Notification
    from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

    space = make_space("f2-review-late-emitter")
    with django_capture_on_commit_callbacks(execute=True):
        emit_notification(space, event="stocktake.completed", title="Staff alert")
        if change == "module_off":
            space.enabled_modules = [key for key in space.enabled_modules if key != "notifications"]
            space.save(update_fields=["enabled_modules"])
        else:
            close_gate(space, make_actor("f2-review-emitter-gate"))
    assert not Notification.objects.filter(makerspace=space).exists()
    assert not NotificationInboxRow.objects.filter(makerspace=space).exists()


def test_personal_mirror_failure_keeps_the_original_legacy_alert(monkeypatch, django_capture_on_commit_callbacks):
    from apps.notifications.emit import emit_notification
    from apps.notifications.models import Notification

    space = make_space("f2-review-fail-safe-mirror")
    def fail(*args):
        raise RuntimeError("Personal mirror unavailable")
    monkeypatch.setattr("apps.notifications.legacy_inbox.mirror_legacy_staff", fail)
    with django_capture_on_commit_callbacks(execute=True):
        emit_notification(space, event="stocktake.completed", title="Staff alert")
    assert Notification.objects.get(makerspace=space).title == "Staff alert"


def test_service_retry_cannot_follow_a_spoofed_cross_tenant_instance():
    space, foreign = make_space("f2-review-retry"), make_space("f2-review-foreign")
    actor = make_member("f2-review-retry-staff", space)
    row = NotificationDeliveryLog.objects.create(
        makerspace=foreign, channel="slack", feature="bookings", event="confirmed", status="failed",
    )
    row.makerspace = space
    with pytest.raises(NotFound):
        retry_delivery(actor, row, expected_generation=0)
    row.refresh_from_db()
    assert row.status == "failed" and row.retry_generation == 0
    assert not AuditLog.objects.filter(action="notification.delivery_requeued").exists()


def test_service_retry_checks_module_and_source_gate_before_any_mutation():
    from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
    from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

    space = make_space("f2-review-retry-gates")
    actor = make_member("f2-review-retry-gated-staff", space)
    row = NotificationDeliveryLog.objects.create(
        makerspace=space, channel="slack", feature="bookings", event="confirmed", status="failed",
    )
    modules = list(space.enabled_modules)
    space.enabled_modules = [key for key in modules if key != "slack"]
    space.save(update_fields=["enabled_modules"])
    with pytest.raises(ValidationError):
        retry_delivery(actor, row, expected_generation=0)
    space.enabled_modules = modules
    space.save(update_fields=["enabled_modules"])
    close_gate(space, make_actor("f2-review-gate-owner"))
    with pytest.raises(SourceMigrationGateClosed):
        retry_delivery(actor, row, expected_generation=0)
    row.refresh_from_db()
    assert row.status == "failed" and row.retry_generation == 0
    assert not AuditLog.objects.filter(action="notification.delivery_requeued").exists()


def test_saved_opt_out_survives_notifications_runtime_tombstone(monkeypatch):
    space = make_space("f2-review-retained-pref")
    user = member("f2-review-retained-user", space)
    MemberNotificationPreference.objects.create(
        makerspace=space, user=user, feature="bookings", channel="email", enabled=False,
    )
    monkeypatch.setattr("apps.separability.registry.runtime_active", lambda app: app != "notifications")
    assert blocked_reason(space, user.email, user_id=user.pk, feature="bookings", stream="bookings", event="confirmed") == "email_member_opted_out"
    assert blocked_reason(space, user.email, user_id=user.pk, feature="bookings", stream="account", event="password_reset") == ""


def test_preferences_cannot_enable_a_family_whose_domain_module_is_off():
    from tests.return_helpers import authenticated_client

    space = make_space("f2-review-domain-off")
    enable(space)
    inbox_only(space, "events")
    user = member("f2-review-domain-user", space)
    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=["enabled_modules"])
    response = authenticated_client(user).patch(
        f"/api/v1/notifications/preferences/{space.pk}",
        {"feature": "events", "channel": "in_app", "enabled": True}, format="json",
    )
    assert response.status_code == 400
    assert not MemberNotificationPreference.objects.filter(user=user).exists()


def test_revoked_personal_membership_is_not_restored_by_delegated_staff_actions(monkeypatch):
    from tests.return_helpers import authenticated_client

    space = make_space("f2-review-revoked-delegate")
    enable(space)
    user = member("f2-review-revoked-user", space)
    MakerspaceMembership.objects.filter(makerspace=space, user=user).update(status="revoked")
    # Simulate the independent organization action grant, leaving real local status/RBAC queries intact.
    monkeypatch.setattr("apps.accounts.rbac.effective_actions", lambda *args: {"manage_makerspace"})
    client = authenticated_client(user)
    assert client.get(f"/api/v1/notifications/inbox/{space.pk}").status_code == 403
    response = client.patch(f"/api/v1/notifications/preferences/{space.pk}",
                            {"feature": "bookings", "channel": "email", "enabled": False}, format="json")
    assert response.status_code == 403
    assert not MemberNotificationPreference.objects.filter(user=user).exists()


def test_suppression_still_applies_to_hidden_tenant_custody_mail():
    space, other = make_space("f2-review-hidden"), make_space("f2-review-unsuppressed")
    user = member("f2-review-hidden-user", space)
    EmailSuppression.objects.create(
        makerspace=space, address_hash=address_hash(space.pk, user.email), reason="complaint",
    )
    space.superadmin_access_enabled = False
    space.save(update_fields=["superadmin_access_enabled"])
    assert blocked_reason(space, user.email, stream="backup", event="archive_custody_alarm") == "email_address_suppressed"
    assert blocked_reason(other, user.email, stream="backup", event="archive_custody_alarm") == ""


@pytest.mark.parametrize("link", ["//external.test", "/\\external.test", "/\t/external.test", "/\n/external.test", "/\x7fpath"])
def test_inbox_link_rejects_browser_normalization_bypasses(link):
    assert safe_link(link) == ""
    assert safe_link("/m/local/member") == "/m/local/member"
