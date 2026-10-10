"""An `oidc:<slug>` identity can be unlinked like a built-in one (cloud lane).

The link endpoint accepts a configured OIDC provider key, but `DELETE
/api/v1/auth/social/providers/<provider>` only accepted `google` and `apple`, so an OIDC
identity, once linked, answered 404 forever. The last-credential guard in
`unlink_social_identity` applies to it exactly as to the built-ins.
"""

from urllib.parse import quote

import pytest

from apps.accounts.models import User
from apps.accounts.models_oidc import provider_key
from apps.accounts.models_social import SocialIdentity
from apps.audit.models import AuditLog
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db

KEY = provider_key("keycloak")


def _user(username, *, password=True):
    user = User.objects.create_user(username=username, email=f"{username}@example.test")
    if password:
        user.set_password("a-usable-password-123")
    else:
        user.set_unusable_password()
    user.save()
    SocialIdentity.objects.create(user=user, provider=KEY, provider_sub=f"sub-{username}")
    return user


def _delete(user, provider):
    return authenticated_client(user).delete(f"/api/v1/auth/social/providers/{quote(provider)}")


def test_an_oidc_identity_with_a_password_behind_it_can_be_unlinked():
    user = _user("oidc-unlink")

    response = _delete(user, KEY)

    assert response.status_code == 204
    assert not SocialIdentity.objects.filter(user=user).exists()
    assert AuditLog.objects.get(action="auth.social_identity_unlinked").meta == {"provider": KEY}


def test_the_last_credential_guard_still_applies_to_oidc():
    user = _user("oidc-last", password=False)

    response = _delete(user, KEY)

    assert response.status_code == 409
    assert SocialIdentity.objects.filter(user=user, provider=KEY).exists()


@pytest.mark.parametrize("provider", ["github", "oidc:", "oidc:not-linked"])
def test_unknown_or_unlinked_providers_are_still_404(provider):
    user = _user(f"oidc-404-{len(provider)}")

    assert _delete(user, provider).status_code == 404
