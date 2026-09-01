from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import override_settings

from apps.encryption.models import MakerspaceEncryptionKey
from apps.encryption.services import (
    disable_dek,
    get_or_create_active_dek,
    rotate_dek,
)
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import Makerspace
from apps.payments.models import Payment
from apps.tenant_migration import preflight
from apps.tenant_migration.preflight import SourcePreflightError, run_source_preflight
from tests.encryption.conftest import enabled_encryption

pytestmark = pytest.mark.django_db


def make_space(slug):
    return Makerspace.objects.create(name=slug.replace("-", " ").title(), slug=slug)


def make_user(slug):
    return get_user_model().objects.create_user(
        username=slug, email=f"{slug}@example.test"
    )


def make_request(space, user):
    return HardwareRequest.objects.create(
        makerspace=space,
        requester=user,
        requester_username=user.username,
        requester_name="Migration User",
        requester_contact_email=user.email,
    )


def storage_modes(monkeypatch, private="versioned", public_image="quiesced"):
    modes = {
        "private-bucket": private,
        "public-bucket": public_image,
    }
    monkeypatch.setattr(
        preflight.storage,
        "ensure_versioning_or_quiescence",
        lambda bucket: modes[bucket],
    )
    return override_settings(
        AWS_STORAGE_BUCKET_NAME="private-bucket",
        PUBLIC_IMAGE_BUCKET="public-bucket",
    )


def assert_check(expected, callable_):
    with pytest.raises(SourcePreflightError) as caught:
        callable_()
    assert caught.value.check == expected


def test_preflight_refuses_disabled_encryption():
    space = make_space("preflight-disabled-encryption")
    with override_settings(PII_ENCRYPTION_ENABLED=False):
        assert_check("encryption_enabled", lambda: run_source_preflight(space))


def test_preflight_refuses_two_active_keys(monkeypatch):
    space = make_space("preflight-two-active")
    with enabled_encryption():
        keys = [
            MakerspaceEncryptionKey(
                makerspace=space,
                version=version,
                status=MakerspaceEncryptionKey.Status.ACTIVE,
                wrapped_dek=b"x",
                broker_backend="local",
                broker_key_id="test",
            )
            for version in (1, 2)
        ]
        monkeypatch.setattr(preflight, "_keys_for", lambda _space: keys)
        assert_check("exactly_one_active_key", lambda: run_source_preflight(space))


def test_preflight_refuses_live_envelope_using_disabled_version():
    space = make_space("preflight-disabled-live")
    user = make_user("preflight-disabled-live-user")
    with enabled_encryption():
        row = make_request(space, user)
        rotate_dek(space.pk)
        disable_dek(space.pk, 1)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT requester_name FROM hardware_requests_hardwarerequest "
                "WHERE id = %s",
                [row.pk],
            )
            assert cursor.fetchone()[0].startswith("pii:gcm:v1:1:")
        assert_check(
            "disabled_key_live_envelope", lambda: run_source_preflight(space)
        )


def test_preflight_refuses_pending_live_checkout():
    space = make_space("preflight-live-checkout")
    user = make_user("preflight-live-checkout-user")
    with enabled_encryption():
        get_or_create_active_dek(space.pk)
        Payment.objects.bulk_create(
            [
                Payment(
                    makerspace=space,
                    subject_type=Payment.SubjectType.BOOKING,
                    subject_id=999,
                    amount=Decimal("10.00"),
                    currency="usd",
                    created_by=user,
                    external_order_id="checkout-order",
                    checkout_url="https://checkout.example.test/live",
                )
            ]
        )
        assert_check(
            "unresolved_live_checkout", lambda: run_source_preflight(space)
        )


def test_healthy_preflight_reports_each_bucket_storage_mode(monkeypatch):
    space = make_space("preflight-healthy")
    with enabled_encryption(), storage_modes(monkeypatch):
        get_or_create_active_dek(space.pk)

        result = run_source_preflight(space)

    assert result.makerspace_id == space.pk
    assert result.storage_mode == {
        "private": "versioned",
        "public_image": "quiesced",
    }
    assert result.carried_key_versions == ((1, "active"),)
