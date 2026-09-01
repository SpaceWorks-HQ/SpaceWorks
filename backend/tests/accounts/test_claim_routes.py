import pytest
from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from apps.accounts.claim_pre_auth_guard import (
    framework_lifecycle_methods,
    validate_claim_middleware,
)
from apps.accounts.claim_route_guard import (
    ClaimRouteConfigurationError,
    validate_claim_route_matrix,
)
from apps.accounts.claim_route_types import AnonymousRead, ReadOnly, Refused, ID
from apps.accounts.claim_routes import policy_for


class ReadView(APIView):
    def get(self, request):
        return Response({})


def policies(name, *methods):
    return {(name, method): AnonymousRead() for method in methods}


def assert_guard_fails(patterns, matrix, expected):
    with pytest.raises(ClaimRouteConfigurationError, match=expected):
        validate_claim_route_matrix(
            patterns,
            policies=matrix,
            require_all_active=False,
            check_middleware=False,
        )


def test_current_all_active_tree_has_a_complete_claim_matrix(settings):
    assert settings.TOMBSTONED_APPS == frozenset()
    # 72 claim-reachable patterns at D3, plus the D5 claim-redemption endpoint, plus the
    # three organization routes (public detail, public events, invitation redeem). The count
    # is asserted so that adding a member-reachable route is a visible decision here, not
    # only inside the matrix.
    assert len(validate_claim_route_matrix()) == 78


def test_unclassified_runtime_lookup_fails_closed_and_middleware_stays_out():
    assert isinstance(policy_for("future-member-route", "POST"), Refused)
    assert validate_claim_middleware() == []


def test_refused_route_must_run_the_claim_authenticator():
    class AuthenticationBypassView(APIView):
        authentication_classes = []

        def post(self, request):
            return Response({})

    patterns = [
        path(
            "api/v1/auth/bypass",
            AuthenticationBypassView.as_view(),
            name="auth-bypass",
        )
    ]
    matrix = {
        ("auth-bypass", "POST"): Refused("must refuse"),
        ("auth-bypass", "OPTIONS"): AnonymousRead(),
    }
    assert_guard_fails(
        patterns, matrix, "Refused claim route does not authenticate claim tokens"
    )


def test_an_unclassified_route_fails_the_guard():
    patterns = [path("api/v1/member/new", ReadView.as_view(), name="new-member-route")]
    assert_guard_fails(patterns, {}, "Unclassified claim route")


def test_adding_a_method_to_an_existing_route_fails_the_guard():
    class ExpandedView(ReadView):
        def post(self, request):
            return Response({})

    patterns = [path("api/v1/member/existing", ExpandedView.as_view(), name="existing")]
    matrix = policies("existing", "GET", "HEAD", "OPTIONS")
    assert_guard_fails(patterns, matrix, "existing POST")


def test_duplicate_qualified_name_fails_the_guard():
    patterns = [
        path("api/v1/member/one", ReadView.as_view(), name="duplicate"),
        path("api/v1/member/two", ReadView.as_view(), name="duplicate"),
    ]
    matrix = policies("duplicate", "GET", "HEAD", "OPTIONS")
    assert_guard_fails(patterns, matrix, "Duplicate qualified claim route name")


def test_unnamed_pattern_fails_the_guard():
    patterns = [path("api/v1/member/unnamed", ReadView.as_view())]
    assert_guard_fails(patterns, {}, "Unnamed claim-reachable URL pattern")


def test_dispatch_override_fails_the_guard():
    class DispatchingView(ReadView):
        def dispatch(self, request, *args, **kwargs):
            return super().dispatch(request, *args, **kwargs)

    patterns = [path("api/v1/member/dispatch", DispatchingView.as_view(), name="dispatching")]
    matrix = policies("dispatching", "GET", "HEAD", "OPTIONS")
    assert_guard_fails(patterns, matrix, "overrides pre-auth lifecycle hook dispatch")


def test_wildcard_policy_fails_the_guard():
    patterns = [path("api/v1/member/read", ReadView.as_view(), name="read")]
    matrix = {("read", "*"): ReadOnly(tenant=ID)}
    assert_guard_fails(patterns, matrix, "wildcards are forbidden")


def test_callback_wrapper_and_catch_all_fail_the_guard():
    def wrapper(callback):
        def wrapped(*args, **kwargs):
            return callback(*args, **kwargs)

        wrapped.cls = callback.cls
        wrapped.__wrapped__ = callback
        return wrapped

    wrapped = wrapper(ReadView.as_view())
    patterns = [path("api/v1/member/<path:rest>", wrapped, name="catch-all")]
    matrix = policies("catch-all", "GET", "HEAD", "OPTIONS")
    with pytest.raises(ClaimRouteConfigurationError) as exc:
        validate_claim_route_matrix(
            patterns, policies=matrix, require_all_active=False, check_middleware=False
        )
    assert "Catch-all" in str(exc.value)
    assert "callback wrapper" in str(exc.value)


def test_viewset_actions_are_inspected_per_pattern():
    class ExampleViewSet(ViewSet):
        def list(self, request):
            return Response({})

        def create(self, request):
            return Response({})

    callback = ExampleViewSet.as_view({"get": "list", "post": "create"})
    patterns = [path("api/v1/member/viewset", callback, name="viewset")]
    matrix = policies("viewset", "GET", "HEAD", "OPTIONS")
    assert_guard_fails(patterns, matrix, "viewset POST")


def test_installed_framework_graph_includes_every_pre_auth_hook_family():
    assert {
        "__init__",
        "as_view",
        "setup",
        "initialize_request",
        "initial",
        "dispatch",
        "http_method_not_allowed",
        "get_parser_context",
        "get_parsers",
        "get_authenticators",
        "perform_authentication",
        "perform_content_negotiation",
        "determine_version",
        "get_permissions",
        "get_throttles",
    } <= framework_lifecycle_methods()
