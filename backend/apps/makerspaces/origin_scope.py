from urllib.parse import urlsplit

from django.conf import settings
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.origin_scope_routes import (
    MAKERSPACE_KWARG_ROUTES as _MAKERSPACE_KWARG_ROUTES,
    MODEL_LOOKUPS as _MODEL_LOOKUPS,
    request_route_targets,
)
from apps.makerspaces.platform import makerspace_staff_origins
from apps.makerspaces.servability import servable_queryset


NO_STAFF_ORIGIN_SCOPE = object()
AMBIGUOUS_STAFF_ORIGIN_SCOPE = object()


def _origin_candidate(request):
    raw = request.headers.get('Origin') or request.headers.get('Referer', '')
    if not raw:
        return ''
    parts = urlsplit(raw)
    return f'{parts.scheme}://{parts.netloc}' if parts.scheme and parts.netloc else ''


def staff_origin_scope(request):
    origin = _origin_candidate(request)
    if not origin:
        return NO_STAFF_ORIGIN_SCOPE
    if origin in set(settings.PLATFORM_STAFF_ORIGINS):
        return NO_STAFF_ORIGIN_SCOPE
    matches = {
        makerspace.id
        for makerspace in servable_queryset(Makerspace.objects.filter(
            frontend_domain__isnull=False,
        ))
        if origin in makerspace_staff_origins(makerspace)
    }
    if not matches:
        return NO_STAFF_ORIGIN_SCOPE
    if len(matches) > 1:
        return AMBIGUOUS_STAFF_ORIGIN_SCOPE
    return next(iter(matches))


def origin_scoped_makerspace_id(request):
    scope = staff_origin_scope(request)
    if scope not in (NO_STAFF_ORIGIN_SCOPE, AMBIGUOUS_STAFF_ORIGIN_SCOPE):
        return scope
    return getattr(request, 'selected_makerspace_id', None)


def validate_native_makerspace_scope(request, user, grant):
    raw = request.headers.get('X-Makerspace-Id')
    if raw is None:
        return None
    if not _active_attested_grant(user, grant):
        raise PermissionDenied(
            'Native makerspace selection requires an active device grant.'
        )
    try:
        makerspace_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise PermissionDenied('Invalid native makerspace selection.') from exc
    if makerspace_id <= 0 or str(makerspace_id) != str(raw).strip():
        raise PermissionDenied('Invalid native makerspace selection.')

    origin = _origin_candidate(request)
    origin_scope = staff_origin_scope(request)
    if origin:
        if origin_scope in (
            NO_STAFF_ORIGIN_SCOPE,
            AMBIGUOUS_STAFF_ORIGIN_SCOPE,
        ):
            raise PermissionDenied(
                'Browser origin cannot use native makerspace selection.'
            )
        if origin_scope != makerspace_id:
            raise PermissionDenied(
                'Makerspace selection conflicts with browser origin.'
            )

    memberships = servable_queryset(MakerspaceMembership.objects.filter(
        user=user,
        makerspace_id=makerspace_id,
        status='active',
    ), relation="makerspace").select_related('makerspace', 'assigned_role')
    memberships = rbac.hide_from_superadmin(
        user, memberships, field='makerspace_id'
    )
    membership = memberships.first()
    if membership is None:
        raise PermissionDenied('Makerspace selection is not available.')

    url_name, targets, invalid, native_route_allowed = request_route_targets(
        request
    )
    if invalid or not native_route_allowed:
        raise PermissionDenied('Makerspace target could not be resolved.')
    if targets and targets != {makerspace_id}:
        raise PermissionDenied(
            'Makerspace target does not match the selected makerspace.'
        )
    request.selected_makerspace_id = makerspace_id
    request.selected_makerspace_membership = membership
    request.selected_makerspace_route = url_name
    return makerspace_id


def _active_attested_grant(user, grant):
    return bool(
        grant
        and grant.user_id == getattr(user, 'pk', None)
        and grant.status == grant.Status.ACTIVE
        and grant.revoked_at is None
        and grant.attested_at is not None
    )


def require_native_selected_makerspace(request, makerspace_id=None):
    selected = getattr(request, 'selected_makerspace_id', None)
    membership = getattr(request, 'selected_makerspace_membership', None)
    if (
        selected is None
        or membership is None
        or (makerspace_id is not None and selected != makerspace_id)
    ):
        raise PermissionDenied(
            'A matching native makerspace selection is required.'
        )
    return membership


def staff_origin_scope_allows(request, view=None):
    scope = staff_origin_scope(request)
    if scope is NO_STAFF_ORIGIN_SCOPE:
        return True
    if scope is AMBIGUOUS_STAFF_ORIGIN_SCOPE:
        return False
    target = _target_makerspace_id(request, view)
    if target is None:
        return _global_endpoint_allowed(request)
    return target == scope


def object_in_staff_origin_scope(request, obj):
    scope = staff_origin_scope(request)
    if scope is NO_STAFF_ORIGIN_SCOPE:
        return True
    if scope is AMBIGUOUS_STAFF_ORIGIN_SCOPE:
        return False
    target = _object_makerspace_id(obj)
    return target is None or target == scope


def _global_endpoint_allowed(request):
    match = getattr(request, 'resolver_match', None)
    return getattr(match, 'url_name', '') == 'admin-makerspaces'


def _target_makerspace_id(request, view=None):
    _url_name, targets, invalid, _native_route_allowed = request_route_targets(
        request, view
    )
    if invalid or len(targets) != 1:
        return None
    return next(iter(targets))


def _object_makerspace_id(obj):
    makerspace_id = getattr(obj, 'makerspace_id', None)
    if makerspace_id is not None:
        return makerspace_id
    bucket = getattr(obj, 'bucket', None)
    if bucket is not None:
        return getattr(bucket, 'makerspace_id', None)
    print_request = getattr(obj, 'print_request', None)
    if print_request is not None:
        return getattr(print_request, 'makerspace_id', None)
    return None
