"""A6 master switches and social-provider lockout protection.

The rule these tests exist to pin: each new switch is an **additive AND** in front of a
readiness check that already existed. Turning one ON must never make an unconfigured
capability start working, and turning one OFF must not be the only thing standing
between a user and their account.
"""

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.accounts.models_social import (
    PlatformSocialAuthSettings,
    SocialIdentity,
    SocialProvider,
)
from apps.accounts.social_lockout import (
    provider_configured,
    users_locked_out_by_disabling,
)
from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import feature_enabled

pytestmark = pytest.mark.django_db


def space(slug, *, without=()):
    makerspace = Makerspace.objects.create(name=slug.title(), slug=slug)
    if without:
        makerspace.enabled_features = sorted(
            set(makerspace.enabled_features or []) - set(without)
        )
        makerspace.save(update_fields=["enabled_features"])
    return makerspace


# --- the switches are additive, not replacements -------------------------------


def test_payments_master_switch_gates_a_configured_domain():
    from unittest.mock import patch

    from apps.payments.availability import online_payments_enabled

    makerspace = space("a6-payments")
    makerspace.enabled_features = sorted(
        set(makerspace.enabled_features or []) | {"payments.enabled", "payments.bookings"}
    )
    makerspace.save(update_fields=["enabled_features"])

    with patch("apps.payments.availability.resolve_payment_source", return_value=object()):
        assert online_payments_enabled(makerspace, "bookings") is True

        makerspace.enabled_features = sorted(
            set(makerspace.enabled_features) - {"payments.enabled"}
        )
        makerspace.save(update_fields=["enabled_features"])
        assert online_payments_enabled(makerspace, "bookings") is False


def test_payments_master_switch_does_not_bypass_credentials_or_the_domain_feature():
    from unittest.mock import patch

    from apps.payments.availability import online_payments_enabled

    makerspace = space("a6-payments-additive")
    makerspace.enabled_features = sorted(
        set(makerspace.enabled_features or []) | {"payments.enabled", "payments.bookings"}
    )
    makerspace.save(update_fields=["enabled_features"])

    # Master switch on, credentials absent -> still off.
    with patch("apps.payments.availability.resolve_payment_source", return_value=None):
        assert online_payments_enabled(makerspace, "bookings") is False
    # Master switch on, credentials present, domain feature off -> still off.
    with patch("apps.payments.availability.resolve_payment_source", return_value=object()):
        assert online_payments_enabled(makerspace, "events") is False


def test_geofence_switch_off_means_not_checked_never_blocked():
    from apps.presence.geofence import evaluate_geofence

    makerspace = space("a6-geofence", without=("presence.geofence",))
    makerspace.geofence_enabled = True
    makerspace.geofence_latitude = 10
    makerspace.geofence_longitude = 10
    makerspace.save(update_fields=["geofence_enabled", "geofence_latitude", "geofence_longitude"])

    # None == "not checked", the same dormant answer an unconfigured space gives. The
    # geofence is advisory, so a disabled switch can only remove a classification.
    assert evaluate_geofence(makerspace, latitude=10, longitude=10, accuracy=5) is None


def test_geofence_switch_on_still_requires_configuration():
    from apps.presence.geofence import evaluate_geofence

    makerspace = space("a6-geofence-unconfigured")
    assert feature_enabled(makerspace, "presence.geofence") is True

    assert evaluate_geofence(makerspace, latitude=10, longitude=10, accuracy=5) is None


def test_bootstrap_omits_the_geofence_flag_when_the_switch_is_off():
    from apps.makerspaces.platform import bootstrap_payload

    makerspace = space("a6-geofence-bootstrap", without=("presence.geofence",))
    makerspace.geofence_enabled = True
    makerspace.geofence_latitude = 10
    makerspace.geofence_longitude = 10
    makerspace.save(update_fields=["geofence_enabled", "geofence_latitude", "geofence_longitude"])

    payload = bootstrap_payload(makerspace)

    # Omitted entirely, not sent as false — the byte-for-byte dormant-payload invariant.
    assert "geofence_enabled" not in payload["makerspace"]


def test_push_switch_gates_delivery_without_replacing_the_credential_check():
    from unittest.mock import patch

    from apps.integrations.push import deliver_native_push

    makerspace = space("a6-push", without=("mobile.push",))
    log = type("Log", (), {"makerspace_id": makerspace.pk, "makerspace": makerspace})()

    with patch("apps.integrations.push.PlatformPushSettings") as settings_row:
        assert deliver_native_push(log) is False
        # Short-circuited before the platform credentials were even loaded.
        settings_row.load.assert_not_called()


# --- social stays platform-scoped ---------------------------------------------


def test_social_sign_in_is_not_a_tenant_feature():
    """Social resolves before a makerspace is selected, so it cannot be tenant-gated.

    A future 'social.google' feature key would be unreachable at the point the provider
    token is verified, and would read as disabled for everyone.
    """
    from apps.makerspaces.capabilities import FEATURES

    assert not [key for key in FEATURES if key.startswith("social")]


def test_provider_configured_reads_every_client_id_not_just_web():
    row = PlatformSocialAuthSettings(google_android_client_id="android-id")

    assert provider_configured(row, SocialProvider.GOOGLE) is True
    assert provider_configured(row, SocialProvider.APPLE) is False


# --- lockout protection --------------------------------------------------------


def social_only_user(username, provider=SocialProvider.GOOGLE):
    user = User.objects.create_user(username=username, email=f"{username}@example.test")
    user.set_unusable_password()
    user.save(update_fields=["password"])
    SocialIdentity.objects.create(user=user, provider=provider, provider_sub=username)
    return user


def test_a_social_only_user_counts_as_locked_out():
    social_only_user("google-only")

    assert [u.username for u in users_locked_out_by_disabling(SocialProvider.GOOGLE)] == [
        "google-only"
    ]


def test_a_user_with_a_password_or_another_provider_is_not_locked_out():
    with_password = User.objects.create_user(
        username="has-password", email="hp@example.test", password="password"
    )
    SocialIdentity.objects.create(
        user=with_password, provider=SocialProvider.GOOGLE, provider_sub="hp"
    )
    both = social_only_user("has-both")
    SocialIdentity.objects.create(user=both, provider=SocialProvider.APPLE, provider_sub="hb")

    assert users_locked_out_by_disabling(SocialProvider.GOOGLE) == []


def test_an_inactive_user_does_not_block_an_admin_change():
    user = social_only_user("inactive-social")
    User.objects.filter(pk=user.pk).update(is_active=False)

    assert users_locked_out_by_disabling(SocialProvider.GOOGLE) == []


def test_the_admin_form_refuses_to_disable_a_providers_last_credential():
    from apps.accounts.admin_social import PlatformSocialAuthSettingsForm

    PlatformSocialAuthSettings.objects.create(pk=1, google_web_client_id="web-id")
    social_only_user("stranded")

    form = PlatformSocialAuthSettingsForm(
        data={"google_web_client_id": "", "apple_native_app_ids": "[]"},
        instance=PlatformSocialAuthSettings.objects.get(pk=1),
    )

    assert form.is_valid() is False
    assert "lock out 1 account" in " ".join(form.errors["__all__"])


def test_the_admin_form_allows_disabling_when_nobody_is_stranded():
    from apps.accounts.admin_social import PlatformSocialAuthSettingsForm

    PlatformSocialAuthSettings.objects.create(pk=1, google_web_client_id="web-id")
    User.objects.create_user(username="safe", email="s@example.test", password="password")

    form = PlatformSocialAuthSettingsForm(
        data={"google_web_client_id": "", "apple_native_app_ids": "[]"},
        instance=PlatformSocialAuthSettings.objects.get(pk=1),
    )

    assert form.is_valid() is True, form.errors


def test_enabling_a_provider_is_never_blocked():
    from apps.accounts.admin_social import PlatformSocialAuthSettingsForm

    PlatformSocialAuthSettings.objects.create(pk=1)
    social_only_user("stranded-on-apple", provider=SocialProvider.APPLE)

    form = PlatformSocialAuthSettingsForm(
        data={"google_web_client_id": "new-web-id", "apple_native_app_ids": "[]"},
        instance=PlatformSocialAuthSettings.objects.get(pk=1),
    )

    assert form.is_valid() is True, form.errors


# --- the upgrade path ----------------------------------------------------------


def test_existing_makerspaces_keep_the_switches_through_the_backfill():
    from django.db import connection
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(connection)
    assert ("makerspaces", "0051_backfill_a6_master_feature_switches") in loader.graph.nodes


def test_the_switches_default_on_for_a_new_makerspace():
    makerspace = space("a6-defaults")

    for key in ("payments.enabled", "mobile.push", "presence.geofence"):
        assert feature_enabled(makerspace, key) is True, key
