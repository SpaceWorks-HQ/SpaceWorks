import hashlib
import hmac
import json
import time

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.integrations.email_preferences import suppressed
from apps.integrations.models import EmailSuppression, EmailLog
from apps.integrations.models_timing import NotificationTimingPolicy
from apps.integrations.dispatch import dispatch_email
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db
SECRET = 'test-inbound-signing-secret-0123456789'


def setup():
    space = make_space('bounce-wp3')
    policy = NotificationTimingPolicy(makerspace=space)
    policy.set_bounce_secret(SECRET)
    policy.save()
    assert policy.bounce_secret != SECRET
    return space


def deliver(space, *, secret=SECRET, timestamp=None, reason='bounce', body=None):
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    raw = body or json.dumps({'event_id': 'evt_bounce', 'address': 'Member@Example.test', 'reason': reason})
    signature = hmac.new(secret.encode(), stamp.encode() + b'.' + raw.encode(), hashlib.sha256).hexdigest()
    return APIClient().post(reverse('email-bounce-webhook', kwargs={'makerspace_id': space.pk}), raw,
        content_type='application/json', HTTP_X_SPACEWORKS_TIMESTAMP=stamp, HTTP_X_SPACEWORKS_SIGNATURE=signature)


def test_signed_hard_bounce_is_idempotent_private_and_honoured_at_dispatch():
    space = setup()
    assert deliver(space).status_code == deliver(space).status_code == 200
    row = EmailSuppression.objects.get(makerspace=space)
    assert row.reason == 'bounce' and row.created_by_id is None
    assert 'Member@Example.test' not in row.address_hash
    assert AuditLog.objects.filter(action='email.suppressed_provider').count() == 1
    log = dispatch_email(makerspace=space, to_email='member@example.test', subject='Safety',
                         text_body='Return tool', stream='hardware', event='return_reminder', sync=True)
    assert log.status == EmailLog.Status.SKIPPED and log.error == 'email_address_suppressed'
    assert not suppressed(make_space('other-bounce-wp3'), 'member@example.test')


def test_forgery_expired_timestamp_and_signature_from_another_tenant_are_refused():
    space = setup()
    assert deliver(space, secret='forged').status_code == 403
    assert deliver(space, timestamp=int(time.time()) - 301).status_code == 403
    assert deliver(make_space('unsigned-space-wp3')).status_code == 403
    assert not EmailSuppression.objects.exists()


def test_complaint_upgrades_bounce_without_duplicate_audit_and_soft_bounce_is_invalid():
    space = setup()
    assert deliver(space).status_code == 200
    assert deliver(space, reason='complaint').status_code == 200
    assert deliver(space, reason='complaint').status_code == 200
    assert EmailSuppression.objects.get().reason == 'complaint'
    assert AuditLog.objects.filter(action='email.suppressed_provider').count() == 2
    assert deliver(space, reason='soft_bounce').status_code == 400
