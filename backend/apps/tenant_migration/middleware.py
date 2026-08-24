from contextlib import ExitStack

from django.http import JsonResponse
from django.urls import Resolver404, resolve

from apps.makerspaces.models import Makerspace
from apps.makerspaces.origin_scope import origin_scoped_makerspace_id
from apps.makerspaces.origin_scope_routes import authoritative_route_resolution
from apps.makerspaces.servability import servable_queryset
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
        makerspace_ids = _makerspace_ids(request, match)
        try:
            refusal_exempt = match.view_name in HTTP_EXEMPTIONS
            if makerspace_ids:
                with ExitStack() as locks:
                    lock = shared_session if refusal_exempt else boundary_tenant_write
                    for makerspace_id in makerspace_ids:
                        locks.enter_context(lock(makerspace_id))
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


def _makerspace_ids(request, match):
    selected = getattr(request, "selected_makerspace_id", None)
    if selected is not None:
        return (selected,)

    # Gate resolution is advisory: failures fall through to an unscoped lock. The
    # middleware must never decide whether a route exists or who may call it.
    targets, route_recognized = authoritative_route_resolution(request)
    if targets:
        return tuple(sorted(targets))

    identifier = match.kwargs.get("makerspace_slug")
    if identifier is not None:
        makerspace_id = _public_identifier_makerspace_id(identifier)
        return (makerspace_id,) if makerspace_id is not None else ()

    public_code = match.kwargs.get("public_code")
    if public_code is not None:
        try:
            makerspace_id = Makerspace.objects.filter(
                public_code__iexact=str(public_code or ""),
                lifecycle_state=Makerspace.LifecycleState.ACTIVE,
            ).values_list("pk", flat=True).first()
        except Exception:
            makerspace_id = None
        return (makerspace_id,) if makerspace_id is not None else ()
    if route_recognized:
        # A known object/path route that did not resolve must retain the view's own
        # 404/403 outcome. Neither Origin nor X-Makerspace-Id may substitute a lock.
        return ()

    try:
        origin_scope = origin_scoped_makerspace_id(request)
    except Exception:
        origin_scope = None
    if isinstance(origin_scope, int):
        return (origin_scope,)
    return ()


def _public_identifier_makerspace_id(identifier):
    """Resolve public slugs/codes without raising or changing the eventual view error."""
    value = str(identifier or "").strip()
    if not value:
        return None
    try:
        by_slug = servable_queryset(
            Makerspace.objects.filter(slug=value)
        ).values_list("pk", flat=True).first()
        if by_slug is not None:
            return by_slug
        return servable_queryset(
            Makerspace.objects.filter(public_code__iexact=value)
        ).values_list("pk", flat=True).first()
    except Exception:
        return None


def _locked_response(exc):
    payload = {"detail": str(exc), "code": exc.code}
    if getattr(exc, "purpose", None):
        payload["purpose"] = exc.purpose
    return JsonResponse(payload, status=423)
