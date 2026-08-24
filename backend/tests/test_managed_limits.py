from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.conf import settings
from django.db import close_old_connections, transaction
from django.test import override_settings
from rest_framework.serializers import ValidationError
from rest_framework.test import APIRequestFactory

from apps.accounts.models import User
from apps.admin_api.serializers_makerspaces import MakerspaceSerializer
from apps.inventory.models import InventoryProduct
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db


@pytest.fixture
def makerspace():
    return Makerspace.objects.create(name="Managed Limits Lab", slug="managed-limits")


def create_product(makerspace, name="Quota product", **overrides):
    defaults = {
        "makerspace": makerspace,
        "name": name,
        "is_archived": False,
    }
    defaults.update(overrides)
    return InventoryProduct.objects.create(**defaults)


@override_settings(PLATFORM_DOMAIN_SUFFIX="")
def test_self_host_limits_are_completely_dormant(makerspace):
    makerspace.resource_limit_overrides = {
        key: True if key == "custom_domain" else 0
        for key in limits.KNOWN_LIMIT_KEYS
    }

    for key in limits.KNOWN_LIMIT_KEYS:
        assert limits.resource_limit(makerspace, key) is None
        limits.check_quota(makerspace, key, adding=10_000)

    assert limits.custom_domain_allowed(makerspace) is True


@override_settings(PLATFORM_DOMAIN_SUFFIX=".space-works.tech")
def test_managed_product_default_and_inclusive_boundary(makerspace):
    assert limits.resource_limit(makerspace, "products") == 500
    assert settings.MANAGED_RESOURCE_LIMITS["products"] == 500

    makerspace.resource_limit_overrides = {"products": 2}
    makerspace.save(update_fields=["resource_limit_overrides"])
    create_product(makerspace, "First product")

    with transaction.atomic():
        limits.check_quota(makerspace, "products", adding=1)

    create_product(makerspace, "Second product")
    with transaction.atomic(), pytest.raises(ValidationError):
        limits.check_quota(makerspace, "products", adding=1)


@override_settings(PLATFORM_DOMAIN_SUFFIX=".space-works.tech")
def test_per_space_override_can_lift_or_lower_product_cap(makerspace):
    makerspace.resource_limit_overrides = {"products": 1000}
    assert limits.resource_limit(makerspace, "products") == 1000

    makerspace.resource_limit_overrides = {"products": 0}
    assert limits.resource_limit(makerspace, "products") == 0
    with transaction.atomic(), pytest.raises(ValidationError):
        limits.check_quota(makerspace, "products", adding=1)


@override_settings(PLATFORM_DOMAIN_SUFFIX=".space-works.tech")
@pytest.mark.parametrize("unlimited", [None, -1])
def test_null_and_minus_one_overrides_mean_unlimited(makerspace, unlimited):
    makerspace.resource_limit_overrides = {"products": unlimited}
    create_product(makerspace)

    assert limits.resource_limit(makerspace, "products") is None
    limits.check_quota(makerspace, "products", adding=10_000)


@override_settings(PLATFORM_DOMAIN_SUFFIX=".space-works.tech")
def test_missing_override_key_falls_through_to_default(makerspace):
    makerspace.resource_limit_overrides = {"machines": 99}

    assert limits.resource_limit(makerspace, "products") == 500


@override_settings(PLATFORM_DOMAIN_SUFFIX=".space-works.tech")
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [({}, False), ({"custom_domain": True}, True)],
)
def test_managed_custom_domain_permission_uses_override(
    makerspace, overrides, expected
):
    makerspace.resource_limit_overrides = overrides

    assert limits.custom_domain_allowed(makerspace) is expected


@override_settings(PLATFORM_DOMAIN_SUFFIX="")
def test_self_host_custom_domain_is_allowed_despite_override(makerspace):
    makerspace.resource_limit_overrides = {"custom_domain": False}

    assert limits.custom_domain_allowed(makerspace) is True


def test_barrel_self_host_patch_controls_every_split_limit_module(
    makerspace, monkeypatch
):
    """The historical barrel patch point must govern core, usage and reservations."""
    makerspace.resource_limit_overrides = {
        "products": 0,
        "custom_domain": False,
    }

    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    assert limits.resource_limit(makerspace, "products") == 0
    assert limits.custom_domain_allowed(makerspace) is False

    monkeypatch.setattr(limits, "is_self_host", lambda: True)
    assert limits.resource_limit(makerspace, "products") is None
    assert limits.custom_domain_allowed(makerspace) is True

    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    monkeypatch.setattr(limits, "resource_limit", lambda _space, _channel: 0)
    assert limits.reserve_notification_quota(makerspace, "slack") is False

    monkeypatch.setattr(limits, "is_self_host", lambda: True)
    assert limits.reserve_notification_quota(makerspace, "slack") is True


def test_override_validator_returns_cleaned_valid_dict():
    value = {"products": 5, "storage": None, "custom_domain": False}

    assert limits.validate_resource_limit_overrides(value) == value


def test_override_validator_rejects_unknown_key():
    with pytest.raises(ValidationError, match="Unknown resource limit key"):
        limits.validate_resource_limit_overrides({"unknown": 1})


@pytest.mark.parametrize("invalid", [True, "5", 1.5, -2])
def test_override_validator_rejects_invalid_numeric_values(invalid):
    with pytest.raises(ValidationError):
        limits.validate_resource_limit_overrides({"products": invalid})


@pytest.mark.parametrize("valid", [0, 5, -1, None])
def test_override_validator_accepts_valid_numeric_values(valid):
    assert limits.validate_resource_limit_overrides({"products": valid}) == {
        "products": valid
    }


@pytest.mark.parametrize("invalid", [1, "true", None])
def test_override_validator_rejects_non_boolean_custom_domain(invalid):
    with pytest.raises(ValidationError):
        limits.validate_resource_limit_overrides({"custom_domain": invalid})


@pytest.mark.parametrize("valid", [True, False])
def test_override_validator_accepts_boolean_custom_domain(valid):
    assert limits.validate_resource_limit_overrides({"custom_domain": valid}) == {
        "custom_domain": valid
    }


def _serializer_for(makerspace, actor, overrides):
    request = APIRequestFactory().patch("/")
    request.user = actor
    return MakerspaceSerializer(
        makerspace,
        data={"resource_limit_overrides": overrides},
        partial=True,
        context={"request": request},
    )


def test_non_superadmin_cannot_set_resource_limit_overrides(makerspace):
    actor = User.objects.create_user(username="ordinary-manager", password="x")
    serializer = _serializer_for(makerspace, actor, {"products": 10})

    assert serializer.is_valid() is False
    assert "Only a superadmin" in str(
        serializer.errors["resource_limit_overrides"][0]
    )


def test_superadmin_can_save_resource_limit_overrides(makerspace):
    actor = User.objects.create_superuser(username="limits-super", password="x")
    serializer = _serializer_for(
        makerspace, actor, {"products": 10, "custom_domain": True}
    )

    assert serializer.is_valid(), serializer.errors
    serializer.save()
    makerspace.refresh_from_db()
    assert makerspace.resource_limit_overrides == {
        "products": 10,
        "custom_domain": True,
    }


@override_settings(PLATFORM_DOMAIN_SUFFIX=".space-works.tech")
@pytest.mark.django_db(transaction=True)
def test_concurrent_product_creates_are_serialized_at_quota_boundary(makerspace):
    makerspace.resource_limit_overrides = {"products": 1}
    makerspace.save(update_fields=["resource_limit_overrides"])
    barrier = Barrier(2)

    def create_at_boundary(index):
        close_old_connections()
        barrier.wait()
        try:
            with transaction.atomic():
                current_space = Makerspace.objects.get(pk=makerspace.pk)
                limits.check_quota(current_space, "products", adding=1)
                create_product(current_space, f"Concurrent product {index}")
        except ValidationError:
            result = "limited"
        else:
            result = "created"
        finally:
            close_old_connections()
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create_at_boundary, range(2)))

    assert sorted(results) == ["created", "limited"]
    assert InventoryProduct.objects.filter(makerspace=makerspace).count() == 1
