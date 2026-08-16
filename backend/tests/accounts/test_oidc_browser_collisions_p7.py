import pytest
from django.db import IntegrityError
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from apps.accounts.models import OidcBrowserAttempt, PlatformLoginMethods, User
from apps.accounts.models_social import SocialIdentity
from apps.accounts.serializers_social import SocialLinkSerializer, SocialNonceSerializer
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from tests.accounts.claim_helpers_p7 import redeemed_claim
from tests.accounts.oidc_browser_helpers import ORIGIN, make_provider, metadata, start

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def oidc_environment(settings, monkeypatch):
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN]
    settings.AUTH_COOKIE_SECURE = False


def walk_in(suffix="target"):
    space = Makerspace.objects.create(name=f"OIDC {suffix}", slug=f"oidc-{suffix}")
    user = User(
        username=f"oidc-{suffix}",
        email=f"{suffix}@example.test",
        display_name=f"Walk-in {suffix}",
        is_walk_in=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    user.set_unusable_password()
    user.save()
    membership = MakerspaceMembership.objects.create(
        makerspace=space,
        user=user,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
    )
    return space, user, membership


def prepared_callback(monkeypatch, *, target=None, claims=None):
    provider = make_provider()
    monkeypatch.setattr("apps.accounts.views_oidc_browser.discover", lambda _: metadata(provider))
    monkeypatch.setattr("apps.accounts.views_oidc_browser.exchange_code", lambda *a, **k: "id-token")
    if target is None:
        started = start(APIClient())
    else:
        space, user, _membership = target
        started = start(APIClient(), email=user.email, makerspace_slug=space.slug)
        attempt = OidcBrowserAttempt.objects.get()
        assert attempt.intended_user_id == user.pk
    asserted = claims or {
        "sub": "provider-subject",
        "email": target[1].email if target else "fresh@example.test",
        "email_verified": True,
        "allow_auto_link": True,
    }
    monkeypatch.setattr(
        "apps.accounts.views_oidc_browser.verify_oidc_token", lambda *a, **k: asserted
    )
    return provider, started


def callback(started):
    return APIClient().post(
        "/api/v1/auth/social/oidc/callback",
        {"code": "code", "state": started.data["state"], "nonce": started.data["nonce"]},
        format="json",
        HTTP_ORIGIN=ORIGIN,
    )


def assert_unchanged(response, target):
    target.refresh_from_db()
    assert response.status_code == 409
    assert "refresh_token" not in response.cookies
    assert target.is_walk_in is True


def test_transition_refuses_subject_linked_to_another_user(monkeypatch):
    target = walk_in("subject-target")
    provider, started = prepared_callback(monkeypatch, target=target)
    other = User.objects.create_user(username="subject-other", email="other@example.test")
    SocialIdentity.objects.create(user=other, provider=provider.provider_key, provider_sub="provider-subject")

    response = callback(started)

    assert_unchanged(response, target[1])
    assert response.data["code"] == "identity_conflict"
    assert SocialIdentity.objects.get(provider_sub="provider-subject").user == other


def test_transition_refuses_asserted_email_owned_by_another_user(monkeypatch):
    target = walk_in("email-target")
    other = User.objects.create_user(username="email-other", email="other-email@example.test")
    _provider, started = prepared_callback(
        monkeypatch,
        target=target,
        claims={"sub": "new-subject", "email": other.email, "email_verified": True},
    )

    response = callback(started)

    assert_unchanged(response, target[1])
    assert response.data["code"] == "identity_conflict"
    assert not SocialIdentity.objects.exists()


def test_transition_refuses_a_different_subject_already_on_target(monkeypatch):
    target = walk_in("linked-target")
    provider, started = prepared_callback(monkeypatch, target=target)
    SocialIdentity.objects.create(
        user=target[1], provider=provider.provider_key, provider_sub="old-subject"
    )

    response = callback(started)

    assert_unchanged(response, target[1])
    assert response.data["code"] == "provider_already_linked"
    assert SocialIdentity.objects.get().provider_sub == "old-subject"


def test_unique_constraint_race_rolls_back_before_session(monkeypatch):
    target = walk_in("race-target")
    _provider, started = prepared_callback(monkeypatch, target=target)

    def lose_race(*args, **kwargs):
        raise IntegrityError("concurrent identity winner")

    monkeypatch.setattr(SocialIdentity.objects, "create", lose_race)
    response = callback(started)

    assert_unchanged(response, target[1])
    assert response.data["code"] == "identity_conflict"
    assert not BlacklistedToken.objects.filter(token__user=target[1]).exists()


def test_oidc_transition_revokes_claim_session_and_every_refresh(monkeypatch):
    harness = redeemed_claim("oidc-transition")
    provider = make_provider()
    monkeypatch.setattr("apps.accounts.views_oidc_browser.discover", lambda _: metadata(provider))
    monkeypatch.setattr("apps.accounts.views_oidc_browser.exchange_code", lambda *a, **k: "id-token")
    monkeypatch.setattr(
        "apps.accounts.views_oidc_browser.verify_oidc_token",
        lambda *a, **k: {
            "sub": "transition-subject",
            "email": harness.member.email,
            "email_verified": True,
            "allow_auto_link": True,
        },
    )
    started = start(harness.claim_client)

    response = callback(started)

    assert response.status_code == 200, response.data
    assert response.data["outcome"] == "transitioned"
    harness.member.refresh_from_db()
    harness.claim.refresh_from_db()
    assert harness.member.is_walk_in is False
    assert harness.member.email_verified_at is not None
    assert harness.claim.revoked_at is not None
    outstanding = OutstandingToken.objects.filter(user=harness.member)
    assert outstanding.exists()
    assert BlacklistedToken.objects.filter(token__in=outstanding).count() == outstanding.count() - 1


def test_claim_session_can_bind_only_its_own_walk_in(monkeypatch):
    harness = redeemed_claim("oidc-own-binding")
    other = walk_in("different-walk-in")
    provider = make_provider()
    monkeypatch.setattr("apps.accounts.views_oidc_browser.discover", lambda _: metadata(provider))

    started = start(
        harness.claim_client,
        email=other[1].email,
        makerspace_slug=other[0].slug,
    )

    assert started.status_code == 200
    attempt = OidcBrowserAttempt.objects.get()
    assert attempt.intended_user_id == harness.member.pk
    assert attempt.intended_membership_id == harness.membership.pk


def test_no_local_match_never_creates_when_self_registration_is_disabled(monkeypatch):
    methods = PlatformLoginMethods.load()
    methods.self_registration_enabled = False
    methods.save(update_fields=["self_registration_enabled"])
    _provider, started = prepared_callback(monkeypatch)

    response = callback(started)

    assert response.status_code == 403
    assert response.data["code"] == "registration_disabled"
    assert "refresh_token" not in response.cookies
    assert not User.objects.filter(email="fresh@example.test").exists()


def test_transition_respects_provider_auto_link_switch(monkeypatch):
    target = walk_in("auto-link-off")
    _provider, started = prepared_callback(
        monkeypatch,
        target=target,
        claims={
            "sub": "auto-link-off-subject",
            "email": target[1].email,
            "email_verified": True,
            "allow_auto_link": False,
        },
    )

    response = callback(started)

    assert_unchanged(response, target[1])
    assert response.data["code"] == "account_link_required"


def test_both_social_serializers_accept_a_configured_oidc_provider():
    make_provider()
    nonce = SocialNonceSerializer(
        data={
            "provider": "oidc:campus",
            "surface": "member",
            "delivery": "web",
            "client_platform": "web",
        }
    )
    link = SocialLinkSerializer(
        data={
            "provider": "oidc:campus",
            "id_token": "token",
            "nonce": "nonce",
            "client_platform": "web",
        }
    )
    assert nonce.is_valid(), nonce.errors
    assert link.is_valid(), link.errors
