from django.http import Http404, JsonResponse
from django.urls import Resolver404, resolve

from apps.makerspaces.lookup import (
    get_makerspace_by_public_code,
    get_public_makerspace,
)
from apps.makerspaces.origin_scope import origin_scoped_makerspace_id
from apps.makerspaces.origin_scope_routes import request_route_targets
from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
from apps.tenant_migration.gate_locks import (
    shared_session,
    unscoped_writer_shared_session,
)
from apps.tenant_migration.gate_policy import HTTP_EXEMPTIONS
from apps.tenant_migration.gate_runtime import boundary_tenant_write


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class SourceMigrationGateMiddleware:
    """Hold the source-gate lock around every state-changing HTTP dispatch."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in SAFE_METHODS:
            return self.get_response(request)
        try:
            match = resolve(request.path_info)
        except Resolver404:
            return self.get_response(request)
        request.resolver_match = match
        makerspace_id = _makerspace_id(request, match)
        try:
            refusal_exempt = match.view_name in HTTP_EXEMPTIONS
            if makerspace_id is not None:
                if not refusal_exempt:
                    with boundary_tenant_write(makerspace_id):
                        return self.get_response(request)
                with shared_session(makerspace_id):
                    return self.get_response(request)
            with unscoped_writer_shared_session():
                return self.get_response(request)
        except SourceMigrationGateClosed as exc:
            return _locked_response(exc)

    def process_exception(self, request, exception):
        """Render refusals raised after authentication resolves the tenant."""
        if isinstance(exception, SourceMigrationGateClosed):
            return _locked_response(exception)
        return None


def _makerspace_id(request, match):
    selected = getattr(request, "selected_makerspace_id", None)
    if selected is not None:
        return selected

    # Gate resolution is advisory: failures fall through to an unscoped lock. The
    # middleware must never decide whether a route exists or who may call it.
    try:
        _name, targets, invalid, _recognized = request_route_targets(request)
    except Exception:
        targets, invalid = set(), True
    if not invalid and len(targets) == 1:
        return next(iter(targets))

    identifier = match.kwargs.get("makerspace_slug")
    if identifier is not None:
        try:
            return get_public_makerspace(identifier).pk
        except Http404:
            pass
        except Exception:
            pass

    try:
        origin_scope = origin_scoped_makerspace_id(request)
    except Exception:
        origin_scope = None
    if isinstance(origin_scope, int):
        return origin_scope

    native_scope = _positive_int(request.headers.get("X-Makerspace-Id"))
    if native_scope is not None:
        return native_scope

    public_code = match.kwargs.get("public_code")
    if public_code is not None:
        try:
            makerspace = get_makerspace_by_public_code(
                public_code, allow_archived=True
            )
        except Http404:
            makerspace = None
        except Exception:
            makerspace = None
        return makerspace.pk if makerspace is not None else None
    return None


def _positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 and str(parsed) == str(value).strip() else None


def _locked_response(exc):
    return JsonResponse({"detail": str(exc), "code": exc.code}, status=423)
