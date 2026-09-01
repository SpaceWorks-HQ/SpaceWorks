import uuid

import pytest
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.accounts.token_guard import TokenConfigurationError, validate_token_configuration
from apps.accounts.tokens import (
    SpaceWorksAccessToken,
    SpaceWorksRefreshToken,
    validate_auth_generation,
)
from apps.backup.models import DeploymentRecoveryState


@pytest.mark.django_db
def test_refresh_and_derived_access_are_stamped_with_exact_generation():
    user = User.objects.create_user(username="generation-user")
    state = DeploymentRecoveryState.load()

    refresh = SpaceWorksRefreshToken.for_user(user)
    access = refresh.access_token

    assert refresh["auth_generation"] == str(state.auth_generation)
    assert access["auth_generation"] == str(state.auth_generation)
    assert "surface" not in refresh
    validate_auth_generation(access)


@pytest.mark.django_db
def test_generation_comparison_rejects_missing_and_any_distinct_uuid():
    user = User.objects.create_user(username="generation-exact")
    current = DeploymentRecoveryState.load().auth_generation

    missing = SpaceWorksAccessToken.for_user(user)
    with pytest.raises(AuthenticationFailed, match="different authentication generation"):
        validate_auth_generation(missing)

    different = SpaceWorksAccessToken.for_user(user)
    different["auth_generation"] = str(uuid.UUID(int=(current.int + 1) % (1 << 128)))
    with pytest.raises(AuthenticationFailed, match="different authentication generation"):
        validate_auth_generation(different)


@pytest.mark.django_db
def test_changing_generation_invalidates_an_already_issued_access_token():
    user = User.objects.create_user(username="generation-rotated")
    access = SpaceWorksRefreshToken.for_user(user).access_token
    state = DeploymentRecoveryState.load()
    state.auth_generation = uuid.uuid4()
    state.save(update_fields=("auth_generation", "updated_at"))

    with pytest.raises(AuthenticationFailed):
        validate_auth_generation(access)


def test_token_construction_itself_enforces_exact_generation(monkeypatch):
    from apps.accounts import tokens

    original = str(uuid.uuid4())
    replacement = str(uuid.uuid4())
    monkeypatch.setattr(tokens, "current_auth_generation", lambda: original)
    access = SpaceWorksAccessToken()
    access["auth_generation"] = original
    raw_access = str(access)
    monkeypatch.setattr(tokens, "current_auth_generation", lambda: replacement)

    with pytest.raises(AuthenticationFailed, match="different authentication generation"):
        SpaceWorksAccessToken(raw_access)


def test_token_class_drift_guard_covers_serializers_and_bearer_classes(settings):
    configured = validate_token_configuration()
    assert configured
    assert all(issubclass(item, SpaceWorksAccessToken) for item in configured)

    class InheritedSimpleJwtRefresh(TokenRefreshSerializer):
        pass

    with pytest.raises(TokenConfigurationError, match="non-project refresh class"):
        validate_token_configuration((InheritedSimpleJwtRefresh,))

    settings.SIMPLE_JWT["AUTH_TOKEN_CLASSES"] = (
        "rest_framework_simplejwt.tokens.RefreshToken",
    )
    with pytest.raises(TokenConfigurationError, match="project access-token class"):
        validate_token_configuration(())


def test_project_refresh_class_is_not_installed_as_a_bearer_class(settings):
    assert "apps.accounts.tokens.SpaceWorksRefreshToken" not in settings.SIMPLE_JWT[
        "AUTH_TOKEN_CLASSES"
    ]
    assert SpaceWorksRefreshToken.access_token_class is SpaceWorksAccessToken
    assert not issubclass(SpaceWorksRefreshToken, SpaceWorksAccessToken)
    assert issubclass(SpaceWorksRefreshToken, RefreshToken)
