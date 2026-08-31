"""B2-B boundary caps that do not need request-workflow database setup."""

import pytest
from django.conf import settings as django_settings

from apps.encryption.registry import field_for
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.serializers import RequestSubmitSerializer


def _payload():
    return {
        "contact_name": "Ada Lovelace",
        "contact_email": "Ada@Example.Test",
        "contact_phone": "+44 (0)20 1234 5678",
        "requested_for": "Bench diagnostics",
        "items": [{"product_id": 1, "quantity": 1}],
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contact_name", "x" * 201),
        ("contact_email", f"{'a' * 243}@example.com"),
        ("contact_phone", "x" * 33),
        ("requested_for", "x" * 501),
        ("items", [{"product_id": index, "quantity": 1} for index in range(21)]),
        ("items", [{"product_id": 1, "quantity": 100}]),
    ],
)
def test_anonymous_serializer_rejects_every_hard_cap(field, value):
    payload = _payload()
    payload[field] = value
    serializer = RequestSubmitSerializer(
        data=payload,
        context={"anonymous_submission": True},
    )

    assert not serializer.is_valid()
    assert field in serializer.errors


@pytest.mark.parametrize("missing_field", ["contact_name", "contact_email"])
def test_anonymous_serializer_requires_name_and_email(missing_field):
    payload = _payload()
    payload.pop(missing_field)
    serializer = RequestSubmitSerializer(
        data=payload,
        context={"anonymous_submission": True},
    )

    assert not serializer.is_valid()
    assert missing_field in serializer.errors


def test_authenticated_contact_fields_are_ignored_before_validation():
    payload = _payload()
    payload.update(
        {
            "contact_name": "x" * 201,
            "contact_email": "not-an-email",
            "contact_phone": "x" * 33,
        }
    )
    serializer = RequestSubmitSerializer(
        data=payload,
        context={"anonymous_submission": False},
    )

    assert serializer.is_valid(), serializer.errors
    assert not set(RequestSubmitSerializer.CONTACT_FIELDS) & serializer.validated_data.keys()


def test_default_anonymous_abuse_rates_and_encryption_limit_are_configured():
    rates = django_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    assert rates["anonymous_request_ip_burst"] == "2/min"
    assert rates["anonymous_request_ip_hour"] == "10/hour"
    assert rates["anonymous_request_email"] == "3/day"
    assert field_for(HardwareRequest, "requester_name").max_length == 200
