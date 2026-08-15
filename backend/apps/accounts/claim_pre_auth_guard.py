"""Pre-authentication lifecycle checks for claim-reachable DRF views."""

from functools import lru_cache
import inspect

from django.conf import settings
from django.utils.module_loading import import_string
from django.views import View
from rest_framework.authentication import BaseAuthentication
from rest_framework.negotiation import BaseContentNegotiation
from rest_framework.parsers import BaseParser
from rest_framework.permissions import BasePermission
from rest_framework.renderers import BaseRenderer
from rest_framework.throttling import BaseThrottle
from rest_framework.versioning import BaseVersioning
from rest_framework.views import APIView


# These are the normal extension hooks implemented by the custom policies currently
# configured on claim-reachable routes. Exact class+method matching makes a new hook a
# build failure instead of silently trusting executable pre-auth code.
POLICY_OVERRIDE_ALLOWLIST = {
    "apps.accounts.authentication.SpaceWorksJWTAuthentication": {"authenticate"},
    "apps.accounts.throttles.DeviceLoginThrottle": {"get_cache_key"},
    "apps.accounts.throttles.DeviceLoginUserThrottle": {"get_cache_key"},
    "apps.accounts.throttles.MemberVerificationEmailThrottle": {"get_cache_key"},
    "apps.accounts.throttles.PasswordResetEmailThrottle": {"get_cache_key"},
    "apps.accounts.throttles.PhoneConfirmNumberThrottle": {"get_cache_key"},
    "apps.accounts.throttles.PhoneLoginConfirmThrottle": {"get_cache_key"},
    "apps.accounts.throttles.PhoneOtpNumberThrottle": {"get_cache_key"},
    "apps.accounts.throttles.PhoneOtpRequestThrottle": {"get_cache_key"},
    "apps.apiclients.throttling.ClientTierRateThrottle": {
        "_tier", "allow_request", "get_cache_key"
    },
    "apps.apiclients.throttling.MemberPrincipalRateThrottle": {
        "_tier", "allow_request", "get_cache_key"
    },
    "apps.events.throttles.CollaborativeRegistrationThrottle": {
        "_tier", "allow_request", "get_cache_key"
    },
    "apps.machines.permissions.IsActiveRequester": {"has_permission"},
    "apps.accounts.views_device.IsDeviceAccessToken": {"has_permission"},
    "apps.makerspaces.throttles.MemberImagePresignThrottle": {"get_cache_key"},
}

POLICY_ATTRIBUTES = (
    "authentication_classes",
    "permission_classes",
    "throttle_classes",
    "parser_classes",
    "renderer_classes",
    "content_negotiation_class",
    "versioning_class",
)
POLICY_BASES = (
    BaseAuthentication,
    BasePermission,
    BaseThrottle,
    BaseParser,
    BaseRenderer,
    BaseContentNegotiation,
    BaseVersioning,
)


def validate_pre_auth_route(route):
    view_class = route.callback.cls
    errors = []
    for method_name in framework_lifecycle_methods():
        implementation = _implementation(view_class, method_name)
        if implementation is not None and not _is_framework_callable(implementation):
            errors.append(
                f"{route.view_name} overrides pre-auth lifecycle hook {method_name}"
            )
    errors.extend(_validate_policies(route.view_name, view_class))
    return errors


@lru_cache(maxsize=1)
def framework_lifecycle_methods():
    """Discover the installed Django/DRF request graph from their live callables."""
    callback = APIView.as_view()
    pending = [APIView.dispatch]
    while callback is not None:
        pending.append(callback)
        callback = getattr(callback, "__wrapped__", None)
    seen = set()
    names = {"__init__", APIView.as_view.__name__}
    while pending:
        function = _function(pending.pop())
        if not inspect.isfunction(function) or function in seen:
            continue
        seen.add(function)
        for name in function.__code__.co_names:
            candidate = _function(getattr(APIView, name, None))
            if inspect.isfunction(candidate) and _is_framework_callable(candidate):
                names.add(name)
                pending.append(candidate)
    # ``as_view`` constructs the instance even though calling the closure-bound class
    # does not leave ``__init__`` in co_names.
    return frozenset(names)


def _validate_policies(view_name, view_class):
    errors = []
    for attribute in POLICY_ATTRIBUTES:
        configured = getattr(view_class, attribute, None)
        classes = configured if isinstance(configured, (list, tuple)) else (configured,)
        for policy_class in filter(None, classes):
            if _is_framework_module(policy_class.__module__):
                continue
            key = f"{policy_class.__module__}.{policy_class.__qualname__}"
            actual = _custom_policy_methods(policy_class)
            expected = POLICY_OVERRIDE_ALLOWLIST.get(key)
            if expected is None or actual != expected:
                errors.append(
                    f"{view_name} has unrecognised policy overrides on {key}: "
                    f"{sorted(actual)}"
                )
    return errors


def _custom_policy_methods(policy_class):
    base = next(
        (
            candidate
            for candidate in POLICY_BASES
            if issubclass(policy_class, candidate)
        ),
        None,
    )
    if base is None:
        return {"<unknown-policy-base>"}
    methods = set()
    for owner in policy_class.__mro__:
        if owner is base:
            break
        if _is_framework_module(owner.__module__):
            continue
        methods.update(
            name
            for name, value in owner.__dict__.items()
            if callable(value) and not name.startswith("__")
        )
    return methods


def validate_claim_middleware():
    errors = []
    for dotted_path in settings.MIDDLEWARE:
        middleware = import_string(dotted_path)
        if getattr(middleware, "handles_claim_sessions", False):
            errors.append(f"Middleware may not handle claim sessions: {dotted_path}")
        forbidden = {"authenticate", "authenticate_claim", "dispatch", "dispatch_claim"}
        defined = forbidden & set(middleware.__dict__)
        if defined:
            errors.append(
                f"Middleware may not authenticate or dispatch claim sessions: "
                f"{dotted_path} defines {sorted(defined)}"
            )
    return errors


def _implementation(view_class, name):
    owner = next(
        (candidate for candidate in view_class.__mro__ if name in candidate.__dict__),
        None,
    )
    return None if owner is None else _function(owner.__dict__[name])


def _function(value):
    return getattr(value, "__func__", value)


def _is_framework_callable(value):
    module = getattr(value, "__module__", "")
    return _is_framework_module(module) or value in {
        object.__init__, View.__init__
    }


def _is_framework_module(module):
    return module.startswith("django.") or module.startswith("rest_framework")
