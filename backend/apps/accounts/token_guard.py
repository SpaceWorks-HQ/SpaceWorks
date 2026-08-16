"""Runtime-testable drift guard for SimpleJWT's two independent class hooks."""

from django.conf import settings
from django.urls import get_resolver
from django.utils.module_loading import import_string
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from apps.accounts.tokens import SpaceWorksAccessToken, SpaceWorksRefreshToken


class TokenConfigurationError(AssertionError):
    pass


def validate_token_configuration(serializer_classes=None):
    if serializer_classes is None:
        # Import the project's known serializer module, then discover subclasses. A new
        # project serializer that inherits SimpleJWT's hard-coded RefreshToken is thereby
        # included without maintaining a second correctness list.
        from apps.accounts import serializers as _serializers  # noqa: F401

        # Loading the URL graph imports every live view module.  A token serializer
        # introduced on a reachable project endpoint is therefore present in the
        # subclass graph without maintaining another correctness list.
        get_resolver().url_patterns

        serializer_classes = tuple(
            serializer
            for base in (TokenObtainPairSerializer, TokenRefreshSerializer)
            for serializer in _subclasses(base)
            if serializer.__module__.startswith("apps.")
        )
    errors = []
    for serializer in serializer_classes:
        if not issubclass(serializer, (TokenObtainPairSerializer, TokenRefreshSerializer)):
            errors.append(f"{serializer.__module__}.{serializer.__name__} is not a token serializer")
        elif serializer.token_class is not SpaceWorksRefreshToken:
            errors.append(f"{serializer.__module__}.{serializer.__name__} uses a non-project refresh class")

    configured = tuple(
        import_string(path) for path in settings.SIMPLE_JWT.get("AUTH_TOKEN_CLASSES", ())
    )
    if not configured:
        errors.append("AUTH_TOKEN_CLASSES is empty")
    for token_class in configured:
        if not issubclass(token_class, SpaceWorksAccessToken):
            errors.append(f"{token_class} is not a project access-token class")
    if errors:
        raise TokenConfigurationError("\n".join(errors))
    return configured


def _subclasses(base):
    for child in base.__subclasses__():
        yield child
        yield from _subclasses(child)
