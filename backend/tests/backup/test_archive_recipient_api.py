from types import SimpleNamespace

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup.models import MakerspaceArchiveRecipient
from apps.backup.recipients import encode_unpadded_base64url, enroll_recipient
from apps.backup.throttles import ArchiveRecipientVerificationThrottle
from apps.makerspaces.models import Makerspace, MakerspaceMembership


pytestmark = pytest.mark.django_db

VALID_RECIPIENT = (
    "age1qqqsyqcyq5rqwzqfpg9scrgwpugpzysnzs23v9ccrydpk8qarc0savhh7m"
)
FIRST_NONCE = bytes(range(32))
SECOND_NONCE = bytes(range(32, 64))
ACTIONS = ("verify", "reissue", "revoke", "compromise", "reactivate")


def _manager(makerspace, username):
    actor = User.objects.create_user(
        username=username, access_status=User.AccessStatus.ACTIVE
    )
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return actor


def _client(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def _url(action, makerspace, recipient):
    return reverse(
        f"admin-archive-recipient-{action}",
        kwargs={"makerspace_id": makerspace.pk, "pk": recipient.pk},
    )


def _fake_age(monkeypatch, nonces=(FIRST_NONCE,)):
    values = iter(nonces)
    monkeypatch.setattr(
        "apps.backup.recipients.secrets.token_bytes",
        lambda _size: next(values),
    )
    monkeypatch.setattr(
        "apps.backup.recipients.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=b"ciphertext"),
    )


def test_foreign_manager_cannot_act_by_pk_or_tenant_url():
    own = Makerspace.objects.create(name="Own", slug="recipient-own")
    foreign = Makerspace.objects.create(name="Foreign", slug="recipient-foreign")
    manager = _manager(own, "recipient-own-manager")
    recipient = enroll_recipient(
        makerspace=foreign,
        public_recipient=VALID_RECIPIENT,
        label="Foreign label",
    )
    client = _client(manager)

    for action in ACTIONS:
        payload = (
            {"nonce": encode_unpadded_base64url(FIRST_NONCE)}
            if action == "verify"
            else {}
        )
        own_response = client.post(
            _url(action, own, recipient), payload, format="json"
        )
        foreign_response = client.post(
            _url(action, foreign, recipient), payload, format="json"
        )
        assert own_response.status_code == 404
        assert foreign_response.status_code == 403

    recipient.refresh_from_db()
    assert recipient.verified_at is None
    assert recipient.revoked_at is None
    assert recipient.compromised_at is None


def test_reactivate_allows_revoked_and_refuses_compromised():
    makerspace = Makerspace.objects.create(name="Lifecycle", slug="recipient-lifecycle")
    manager = _manager(makerspace, "recipient-lifecycle-manager")
    revoked = enroll_recipient(
        makerspace=makerspace,
        public_recipient=VALID_RECIPIENT,
        label="Revoked",
    )
    revoked.revoked_at = timezone.now()
    revoked.save(update_fields=("revoked_at",))
    compromised = enroll_recipient(
        makerspace=makerspace,
        public_recipient=VALID_RECIPIENT,
        label="Compromised",
    )
    compromised.revoked_at = timezone.now()
    compromised.compromised_at = timezone.now()
    compromised.save(update_fields=("revoked_at", "compromised_at"))
    client = _client(manager)

    assert client.post(_url("reactivate", makerspace, revoked)).status_code == 200
    assert client.post(_url("reactivate", makerspace, compromised)).status_code == 400
    revoked.refresh_from_db()
    compromised.refresh_from_db()
    assert revoked.revoked_at is None
    assert compromised.revoked_at is not None


def test_every_recipient_action_audits_only_id_and_fingerprint(monkeypatch):
    makerspace = Makerspace.objects.create(name="Audit", slug="recipient-audit")
    manager = _manager(makerspace, "recipient-audit-manager")
    client = _client(manager)
    _fake_age(monkeypatch, (FIRST_NONCE, SECOND_NONCE))
    collection = reverse(
        "admin-archive-recipient-list-create",
        kwargs={"makerspace_id": makerspace.pk},
    )
    label = "arbitrary operator label that must not enter audit meta"

    created = client.post(
        collection,
        {"public_recipient": VALID_RECIPIENT, "label": label},
        format="json",
    )
    assert created.status_code == 201
    recipient = MakerspaceArchiveRecipient.objects.get(
        pk=created.data["recipient"]["id"]
    )
    assert client.post(_url("reissue", makerspace, recipient)).status_code == 200
    assert client.post(
        _url("verify", makerspace, recipient),
        {"nonce": encode_unpadded_base64url(SECOND_NONCE)},
        format="json",
    ).status_code == 200
    for number in (1, 2):
        MakerspaceArchiveRecipient.objects.create(
            makerspace=makerspace,
            public_recipient=f"age1audit-support-{number}",
            fingerprint=f"{number:064x}",
            label=f"Audit support {number}",
            verified_at=timezone.now(),
        )
    assert client.post(_url("revoke", makerspace, recipient)).status_code == 200
    assert client.post(_url("reactivate", makerspace, recipient)).status_code == 200
    assert client.post(_url("compromise", makerspace, recipient)).status_code == 200

    expected = {
        "backup.archive_recipient_added",
        "backup.archive_recipient_challenge_reissued",
        "backup.archive_recipient_verified",
        "backup.archive_recipient_revoked",
        "backup.archive_recipient_reactivated",
        "backup.archive_recipient_compromised",
    }
    logs = AuditLog.objects.filter(action__in=expected)
    assert set(logs.values_list("action", flat=True)) == expected
    for log in logs:
        assert log.meta == {
            "fingerprint": recipient.fingerprint,
            "recipient_id": recipient.pk,
        }
        assert label not in str(log.meta)


def test_verification_attempts_are_throttled_per_recipient(settings, monkeypatch):
    cache.clear()
    rates = {
        **django_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "archive_recipient_verify": "1/min",
    }
    rest_settings = dict(django_settings.REST_FRAMEWORK)
    rest_settings["DEFAULT_THROTTLE_RATES"] = rates
    settings.REST_FRAMEWORK = rest_settings
    monkeypatch.setattr(
        ArchiveRecipientVerificationThrottle, "THROTTLE_RATES", rates
    )
    makerspace = Makerspace.objects.create(name="Throttle", slug="recipient-throttle")
    manager = _manager(makerspace, "recipient-throttle-manager")
    first = enroll_recipient(
        makerspace=makerspace,
        public_recipient=VALID_RECIPIENT,
        label="First",
    )
    second = enroll_recipient(
        makerspace=makerspace,
        public_recipient=VALID_RECIPIENT,
        label="Second",
    )
    client = _client(manager)
    payload = {"nonce": "invalid"}

    assert client.post(_url("verify", makerspace, first), payload).status_code == 400
    assert client.post(_url("verify", makerspace, first), payload).status_code == 429
    assert client.post(_url("verify", makerspace, second), payload).status_code == 400


def test_openapi_documents_all_recipient_routes_and_nonce_encoding():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    paths = schema["paths"]
    root = "/api/v1/admin/makerspace/{makerspace_id}/archive-recipients"

    assert {"get", "post"} <= set(paths[root])
    for suffix in (
        "verify",
        "reissue-challenge",
        "revoke",
        "compromise",
        "reactivate",
    ):
        assert "post" in paths[f"{root}/{{id}}/{suffix}"]
    verify = paths[f"{root}/{{id}}/verify"]["post"]
    assert "unpadded base64url" in verify["description"]
    assert {"200", "400", "401", "403", "404", "409", "429"} <= set(
        verify["responses"]
    )
