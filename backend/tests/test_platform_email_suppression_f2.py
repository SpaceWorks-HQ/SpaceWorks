"""Platform suppression has separate custody from tenant delivery policy."""

import pytest
from django.contrib import admin
from django.db import IntegrityError, transaction
from django.test import RequestFactory

from apps.audit.models import AuditLog
from apps.integrations.admin_suppression import PlatformSuppressionAdmin, PlatformSuppressionForm
from apps.integrations.dispatch import _deliver, dispatch_email
from apps.integrations.email_preferences import address_hash, blocked_reason
from apps.integrations.models import EmailLog, EmailSuppression
from tests.encryption.conftest import enabled_encryption
from tests.return_helpers import make_space, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def platform_encryption():
    with enabled_encryption():
        yield


def test_platform_suppression_blocks_new_and_queued_recovery_mail_without_retaining_pii(platform_encryption, mailoutbox):
    address = "dead-platform@example.test"
    queued = EmailLog.objects.create(
        to_email="", subject="Platform email", text_body="", connection_kind="platform",
    )
    queued.to_email, queued.text_body = address, "Transient recovery token"
    EmailSuppression.objects.create(address_hash=address_hash(None, address), reason="bounce")
    log = dispatch_email(
        to_email=address, subject="Recovery", text_body="Secret reset token",
        connection="platform", persist_body=False, sync=True,
    )
    assert log.status == EmailLog.Status.SKIPPED
    log.refresh_from_db()
    assert (log.to_email, log.subject, log.text_body, log.html_body) == ("", "Platform email", "", "")
    assert _deliver(queued).status == EmailLog.Status.SKIPPED
    assert not mailoutbox


def test_platform_and_tenant_suppression_do_not_cross_custody_boundaries():
    space = make_space("f2-platform-suppression")
    address = "shared@example.test"
    row = EmailSuppression.objects.create(address_hash=address_hash(None, address), reason="complaint")
    assert blocked_reason(None, address.upper()) == "email_address_suppressed"
    assert blocked_reason(space, address) == ""
    row.delete()
    EmailSuppression.objects.create(
        makerspace=space, address_hash=address_hash(space.pk, address), reason="bounce",
    )
    assert blocked_reason(None, address) == ""
    assert blocked_reason(space, address) == "email_address_suppressed"


def test_platform_suppression_uniqueness_is_database_enforced():
    digest = address_hash(None, "duplicate@example.test")
    EmailSuppression.objects.create(address_hash=digest, reason="bounce")
    with pytest.raises(IntegrityError), transaction.atomic():
        EmailSuppression.objects.create(address_hash=digest, reason="complaint")


def test_platform_control_is_superadmin_only_hides_tenant_rows_and_audits_add_delete():
    operator = make_user("f2-platform-suppression-operator", is_superuser=True, is_staff=True)
    request = RequestFactory().post("/control/integrations/emailsuppression/add/")
    request.user = operator
    control = PlatformSuppressionAdmin(EmailSuppression, admin.site)
    form = PlatformSuppressionForm(data={"address": "platform@example.test", "reason": "complaint"})
    assert control.has_add_permission(request)
    assert form.is_valid(), form.errors
    row = form.save(commit=False)
    control.save_model(request, row, form, False)
    assert row.makerspace_id is None and row.created_by == operator
    assert row.address_hash == address_hash(None, "platform@example.test")
    duplicate = PlatformSuppressionForm(data={"address": "PLATFORM@example.test", "reason": "bounce"})
    assert not duplicate.is_valid() and "address" in duplicate.errors
    space = make_space("f2-platform-control-tenant")
    foreign = EmailSuppression.objects.create(
        makerspace=space, address_hash=address_hash(space.pk, "tenant@example.test"), reason="bounce",
    )
    assert list(control.get_queryset(request)) == [row]
    assert not control.has_change_permission(request, row)
    control.delete_queryset(request, control.get_queryset(request))
    assert EmailSuppression.objects.filter(pk=foreign.pk).exists()
    writes = AuditLog.objects.filter(actor=operator, action__startswith="email.platform_")
    assert set(writes.values_list("action", flat=True)) == {"email.platform_suppressed", "email.platform_unsuppressed"}
    assert "platform@example.test" not in str(list(writes.values_list("meta", flat=True)))
    request.user = make_user("f2-platform-suppression-staff", is_staff=True)
    assert not control.has_add_permission(request)
    assert not control.has_view_permission(request)
    assert not control.has_delete_permission(request)
