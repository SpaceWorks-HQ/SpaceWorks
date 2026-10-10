import pytest
from django.core import signing
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.integrations.dispatch import _deliver, dispatch_email
from apps.integrations.email_preferences import address_hash, unsubscribe_headers, unsubscribe_token
from apps.integrations.models import EmailLog, EmailSuppression
from apps.notifications.models import MemberNotificationPreference
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


def setup_space(slug):
    space = make_space(slug)
    space.enabled_features = [*space.enabled_features, "notifications.member_preferences"]
    space.save(update_fields=["enabled_features"])
    return space, make_member(f"{slug}-member", space)


def send(space, user, **kwargs):
    return dispatch_email(makerspace=space, to_email=user.email, recipient_id=user.pk,
        feature="hardware_requests", subject="Update", text_body="Own request update",
        stream="hardware", event=kwargs.pop("event", "request_accepted"), sync=True, **kwargs)


def test_signed_one_click_needs_no_login_and_only_mutes_its_bound_family():
    space, user = setup_space("f2-one-click")
    token = unsubscribe_token(space.pk, user.pk, "bookings")
    path = f"/api/v1/notifications/unsubscribe/{token}"
    client = APIClient()
    response = client.post(path, {"List-Unsubscribe": "One-Click"}, format="multipart")
    # RFC clients use form-urlencoded, not a multipart upload.
    assert response.status_code == 415
    response = client.post(path, "List-Unsubscribe=One-Click", content_type="application/x-www-form-urlencoded")
    assert response.status_code == 200
    assert client.post(path, {"List-Unsubscribe": "One-Click"}, format="json").status_code == 200
    assert MemberNotificationPreference.objects.filter(user=user, feature="bookings", channel="email", enabled=False).count() == 1
    assert not MemberNotificationPreference.objects.filter(user=user, feature="events").exists()
    assert AuditLog.objects.filter(action="notification.unsubscribed", actor=user).exists()
    assert client.get(path).status_code == 405


def test_unsubscribe_refuses_forged_expired_wrong_salt_and_missing_form_value(monkeypatch):
    space, user = setup_space("f2-forgery")
    client = APIClient()
    token = unsubscribe_token(space.pk, user.pk, "bookings")
    def post(value):
        return client.post(f"/api/v1/notifications/unsubscribe/{value}", {"List-Unsubscribe": "One-Click"}, format="json")
    assert post(token + "x").status_code == 400
    forged = signing.dumps({"space": space.pk, "user": user.pk, "feature": "bookings"}, salt="wrong")
    assert post(forged).status_code == 400
    assert client.post(f"/api/v1/notifications/unsubscribe/{token}", {}, format="json").status_code == 400
    monkeypatch.setattr("apps.integrations.email_preferences.TOKEN_MAX_AGE", -1)
    assert post(token).status_code == 400
    assert not MemberNotificationPreference.objects.exists()


def test_headers_are_https_one_click_and_omitted_for_mandatory_mail(settings):
    space, user = setup_space("f2-headers")
    settings.PUBLIC_APP_BASE_URL = "https://makers.example"
    log = EmailLog.objects.create(makerspace=space, recipient=user, feature="bookings",
                                  stream="bookings", event="confirmed", to_email=user.email, subject="Booking")
    headers = unsubscribe_headers(log)
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert headers["List-Unsubscribe"].startswith("<https://makers.example/api/v1/notifications/unsubscribe/")
    log.stream, log.event = "hardware", "return_reminder"
    assert unsubscribe_headers(log) == {}
    log.stream, log.event = "bookings", "confirmed"
    settings.PUBLIC_APP_BASE_URL = "http://localhost:5000"
    assert unsubscribe_headers(log) == {}


def test_suppression_blocks_new_and_queued_mail_including_transactional(settings, mailoutbox):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    space, user = setup_space("f2-suppression")
    queued = EmailLog.objects.create(makerspace=space, recipient=user, to_email=user.email,
        subject="Pending", text_body="Own body", feature="hardware_requests", stream="hardware", event="return_reminder")
    EmailSuppression.objects.create(makerspace=space, address_hash=address_hash(space.pk, user.email.upper()), reason="bounce")
    assert send(space, user).status == "skipped"
    assert _deliver(queued).status == "skipped"
    assert not mailoutbox
    other = make_space("f2-suppression-other")
    assert address_hash(other.pk, user.email) != address_hash(space.pk, user.email)


def test_personal_email_opt_out_is_rechecked_before_delivery_and_safety_cannot_be_muted(settings, mailoutbox):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    space, user = setup_space("f2-optional")
    queued = EmailLog.objects.create(makerspace=space, recipient=user, to_email=user.email,
        subject="Optional", text_body="Own body", feature="hardware_requests", stream="hardware", event="request_accepted")
    MemberNotificationPreference.objects.create(makerspace=space, user=user, feature="hardware_requests", channel="email", enabled=False)
    assert _deliver(queued).status == "skipped"
    assert send(space, user, event="return_reminder").status == "sent"
    assert len(mailoutbox) == 1


def test_manual_suppression_api_is_scoped_audited_and_does_not_echo_address():
    space, manager = setup_space("f2-suppression-admin")
    other = make_space("f2-suppression-foreign")
    client = authenticated_client(manager)
    path = f"/api/v1/integrations/makerspace/{space.pk}/email-suppressions"
    response = client.post(path, {"address": "BOUNCED@example.test", "reason": "complaint"}, format="json")
    assert response.status_code == 201
    assert "BOUNCED" not in str(response.data) and "address" not in response.data
    assert client.get(path).data["count"] == 1
    assert client.get(path.replace(str(space.pk), str(other.pk))).status_code == 404
    assert client.delete(f"{path}/{response.data['id']}").status_code == 204
    assert AuditLog.objects.filter(actor=manager, action="email.suppressed").count() == 1
    assert AuditLog.objects.filter(actor=manager, action="email.unsuppressed").count() == 1


def test_signed_unsubscribe_cannot_mutate_a_frozen_tenant():
    from tests.tenant_migration.source_gate_helpers import close_gate, make_actor
    space, user = setup_space("f2-unsubscribe-frozen")
    close_gate(space, make_actor("f2-unsubscribe-gate"))
    token = unsubscribe_token(space.pk, user.pk, "bookings")
    response = APIClient().post(f"/api/v1/notifications/unsubscribe/{token}",
                                {"List-Unsubscribe": "One-Click"}, format="json")
    assert response.status_code == 423
    assert not MemberNotificationPreference.objects.filter(makerspace=space).exists()
