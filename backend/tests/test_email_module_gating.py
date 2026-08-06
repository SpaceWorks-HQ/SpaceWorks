"""The `email` module gates tenant mail only (plan A5).

The interesting cases are all about what must keep working when a makerspace turns
email off: account recovery, email verification, and overdue-loan reminders. Getting
any of those wrong is silent -- nothing errors, mail just stops.
"""

import pytest
from django.core import mail

from apps.integrations.dispatch import dispatch_email
from apps.integrations.email import send_email_verification_otp, send_password_reset_email
from apps.integrations.models import EmailLog
from apps.integrations.services import EmailRetryError, retry_email_log
from apps.integrations.tasks import deliver_email_task
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import uninstall_module

pytestmark = pytest.mark.django_db


def space(slug, *, email_on=True):
    # The conftest fixture gives a new test makerspace the `everything` profile, so the
    # module starts ON and the disabled case has to be opted into explicitly.
    makerspace = Makerspace.objects.create(name=slug.title(), slug=slug)
    if not email_on:
        uninstall_module(makerspace, "email")
        makerspace.refresh_from_db()
    return makerspace


def send(makerspace, *, stream="membership", event="invitation", sync=True):
    return dispatch_email(
        to_email="member@example.test",
        subject="Hello",
        text_body="Body",
        makerspace=makerspace,
        stream=stream,
        event=event,
        audience="member",
        sync=sync,
    )


# --- the gate ----------------------------------------------------------------


def test_tenant_mail_is_skipped_when_the_module_is_off():
    log = send(space("email-off", email_on=False))

    assert log.status == EmailLog.Status.SKIPPED
    assert mail.outbox == []


def test_tenant_mail_is_delivered_when_the_module_is_on():
    log = send(space("email-on"))

    assert log.status == EmailLog.Status.SENT
    assert len(mail.outbox) == 1


def test_a_skip_is_recorded_rather_than_dropped():
    # The operator has to be able to see what their toggle suppressed.
    makerspace = space("email-recorded", email_on=False)

    log = send(makerspace)

    assert EmailLog.objects.filter(pk=log.pk, makerspace=makerspace).exists()
    assert log.error
    assert log.stream == "membership" and log.event == "invitation"


# --- what a tenant may not switch off ----------------------------------------


def test_password_reset_still_sends_with_the_module_off():
    space("email-reset", email_on=False)

    assert send_password_reset_email("user@example.test", "https://example.test/reset") == 1
    assert len(mail.outbox) == 1


def test_email_verification_still_sends_with_the_module_off():
    # Missing this exemption leaves a new account unable to verify, and therefore
    # unable to join at all.
    space("email-verify", email_on=False)

    assert send_email_verification_otp("user@example.test", "123456") == 1
    assert len(mail.outbox) == 1


def test_return_reminders_still_send_with_the_module_off():
    log = send(space("email-reminder", email_on=False), stream="hardware", event="return_reminder")

    assert log.status == EmailLog.Status.SENT


def test_the_exemption_matches_stream_and_event_not_event_alone():
    # `return_reminder` under a different stream is ordinary tenant mail. Matching on
    # the event name alone would exempt it by accident.
    log = send(space("email-stream-scope", email_on=False), stream="events", event="return_reminder")

    assert log.status == EmailLog.Status.SKIPPED


def test_platform_mail_has_no_tenant_gate():
    # `makerspace=None` mail belongs to no tenant, so no tenant toggle can apply.
    space("email-platform", email_on=False)

    log = dispatch_email(
        to_email="user@example.test", subject="Platform", text_body="Body",
        makerspace=None, stream="account", event="something_else", sync=True,
    )

    assert log.status == EmailLog.Status.SENT


# --- queue, retry and delivery -----------------------------------------------


def test_a_queued_email_is_skipped_if_the_module_is_disabled_before_delivery():
    """Gating dispatch alone would let everything already in flight through."""
    makerspace = space("email-inflight")
    log = send(makerspace, sync=False)
    assert log.status == EmailLog.Status.PENDING

    uninstall_module(makerspace, "email")
    deliver_email_task(log.pk)

    log.refresh_from_db()
    assert log.status == EmailLog.Status.SKIPPED
    assert mail.outbox == []


def test_a_skipped_email_cannot_be_retried():
    from apps.accounts.models import User

    actor = User.objects.create_superuser(
        username="retry-admin", email="ra@example.test", password="password"
    )
    log = send(space("email-retry", email_on=False))

    with pytest.raises(EmailRetryError):
        retry_email_log(actor, log)

    log.refresh_from_db()
    assert log.status == EmailLog.Status.SKIPPED


def test_a_skip_counts_as_neither_delivered_nor_failed():
    # `notify_return_due` returns `bool(delivered_counts)`; counting a skip as a
    # delivery would mark an overdue loan as reminded when nothing was sent.
    from apps.integrations.notify import _dispatch_email_delivery
    from types import SimpleNamespace

    makerspace = space("email-counts", email_on=False)
    delivery = SimpleNamespace(
        to_email="member@example.test", subject="S", text_body="B", html_body="",
        stream="membership", mute_event="invitation", audience="member",
        target="", persist_body=True,
    )
    delivered, failed = {}, {}

    _dispatch_email_delivery(makerspace, "invitation", delivery, True, delivered, failed)

    assert delivered == {} and failed == {}


# --- the upgrade path ---------------------------------------------------------


def test_existing_makerspaces_keep_email_through_the_backfill():
    # `0050` turns the new key on for spaces that predate it. Without it, every
    # existing makerspace would stop sending mail the moment this release deploys.
    from django.db.migrations.loader import MigrationLoader
    from django.db import connection

    loader = MigrationLoader(connection)
    assert ("makerspaces", "0050_enable_email_module_for_existing_makerspaces") in loader.graph.nodes


def test_the_recommended_profile_includes_email():
    from apps.makerspaces.module_profiles import RECOMMENDED, profile_modules

    assert "email" in profile_modules(RECOMMENDED)
