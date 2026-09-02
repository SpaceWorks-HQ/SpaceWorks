from django.apps import apps

from apps.makerspaces.origin_scope_model_lookups import (
    BASE_MODEL_LOOKUPS,
    TARGET_SET_LOOKUPS,
)

MAKERSPACE_KWARG_ROUTES = {
    'admin-maintenance-schedule-list-create': 'makerspace_id',
    'admin-maintenance-log-list-create': 'makerspace_id',
    'admin-bookable-space-list-create': 'makerspace_id',
    'admin-event-list-create': 'makerspace_id',
    'admin-event-series-list-create': 'makerspace_id',
    'admin-event-series-collaboration-inbox': 'makerspace_id',
    'admin-role-capabilities': 'makerspace_id',
    'admin-role-list-create': 'makerspace_id',
    'admin-role-detail': 'makerspace_id',
    'admin-machine-types': 'makerspace_id',
    'admin-machine-type-detail': 'makerspace_id',
    'admin-makerspace-provision-subdomain': 'makerspace_id',
    'admin-makerspace-subdomain-request': 'makerspace_id',
    'admin-api-settings': 'makerspace_id',
    'admin-notification-recipients': 'makerspace_id',
    'admin-notification-rules': 'makerspace_id',
    'admin-machine-service-request-list-create': 'makerspace_id',
}
# These routes have no tenant-bearing path segment by design: each is a listing whose
# queryset is explicitly narrowed by the named makerspace query parameter.
QUERY_SCOPED_ROUTES = {
    'admin-api-key-requests',       # requester-owned API-key requests; ?makerspace=
    'admin-audit-logs',             # tenant audit-log listing; ?makerspace=
    'admin-membership-requests',    # tenant join-request queue; ?makerspace_id=
    'admin-memberships-roster',     # tenant membership roster; ?makerspace_id=
    'admin-needs-fix-shelf',        # tenant repair shelf; ?makerspace=
    'ledger-aggregate',             # superadmin aggregate listing; ?makerspace=
    'ledger-export-aggregate',      # matching aggregate export; ?makerspace=
}
NATIVE_HEADER_GLOBAL_ROUTES = {
    'auth-me',
    'device-grants',
    'device-grant-detail',
    'push-device-list-create',
    'push-device-detail',
}
REQUEST_ACTIONS = {
    'request-accept',
    'request-reject',
    'request-assign-box',
    'request-issue',
    'request-return-due',
    'request-return',
    'guest-admin-request-return',
    'request-timeline',
}
MACHINE_SERVICE_ACTIONS = {
    'admin-machine-service-request-detail',
    'admin-machine-service-request-accept',
    'admin-machine-service-request-reject',
    'admin-machine-service-request-start',
    'admin-machine-service-request-complete',
    'admin-machine-service-request-fail',
    'admin-machine-service-request-collect',
    'admin-machine-service-file-presign',
    'admin-machine-service-file-finalize',
}
MODEL_LOOKUPS = {
    **BASE_MODEL_LOOKUPS,
    **{name: ('hardware_requests.HardwareRequest', 'makerspace_id') for name in REQUEST_ACTIONS},
    **{name: ('machines.MachineServiceRequest', 'makerspace_id') for name in MACHINE_SERVICE_ACTIONS},
}

def request_route_targets(request, view=None):
    url_name, targets, invalid, route_recognized = _authoritative_route_targets(
        request, view
    )
    hints = []
    query = getattr(request, 'query_params', None)
    if query is None:
        query = getattr(request, 'GET', {})
    for key in ('makerspace', 'makerspace_id'):
        value = query.get(key)
        if value in (None, ''):
            continue
        parsed = _positive_int(value)
        invalid = invalid or parsed is None
        if parsed is not None:
            hints.append(parsed)
    if getattr(request, "method", "GET") not in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        body = getattr(request, "data", {})
        if hasattr(body, "get"):
            for key in ("makerspace", "makerspace_id"):
                value = body.get(key)
                if value in (None, ""):
                    continue
                parsed = _positive_int(value)
                invalid = invalid or parsed is None
                if parsed is not None:
                    hints.append(parsed)

    hint_set = set(hints)
    if url_name in TARGET_SET_LOOKUPS:
        invalid = invalid or bool(hint_set - targets)
    else:
        invalid = invalid or len(targets | hint_set) > 1
    target_set = targets | hint_set
    return url_name, target_set, invalid, route_recognized


def authoritative_route_resolution(request, view=None):
    """Return non-raising authoritative targets plus whether the route is known."""
    try:
        _name, targets, invalid, recognized = _authoritative_route_targets(
            request, view
        )
    except Exception:
        return set(), False
    return (targets if recognized and not invalid else set()), recognized


def _authoritative_route_targets(request, view=None):
    match = getattr(request, 'resolver_match', None)
    url_name = getattr(match, 'url_name', '')
    kwargs = dict(getattr(match, 'kwargs', {}) or {})
    kwargs.update(getattr(view, 'kwargs', {}) or {})
    targets = set()
    invalid = False
    registered = MAKERSPACE_KWARG_ROUTES.get(url_name)
    route_recognized = bool(
        registered or 'makerspace_id' in kwargs
        or (url_name == 'admin-makerspace' and 'pk' in kwargs)
        or url_name in MODEL_LOOKUPS or url_name in TARGET_SET_LOOKUPS
        or url_name in QUERY_SCOPED_ROUTES or url_name in NATIVE_HEADER_GLOBAL_ROUTES)
    route_value = None
    if registered:
        route_value = kwargs.get(registered)
        invalid = route_value is None
    elif 'makerspace_id' in kwargs:
        route_value = kwargs.get('makerspace_id')
    elif url_name == 'admin-makerspace' and 'pk' in kwargs:
        route_value = kwargs.get('pk')
    if route_value is not None:
        parsed = _positive_int(route_value)
        invalid = invalid or parsed is None
        if parsed is not None:
            targets.add(parsed)

    if url_name in MODEL_LOOKUPS:
        pk = kwargs.get('pk')
        resolved = _lookup_makerspace_id(url_name, pk) if pk is not None else None
        invalid = invalid or resolved is None
        if resolved is not None:
            targets.add(resolved)
    elif url_name in TARGET_SET_LOOKUPS:
        pk = kwargs.get('pk')
        invalid = invalid or pk is None
        if pk is not None:
            targets.update(_lookup_makerspace_ids(url_name, pk))
    return url_name, targets, invalid, route_recognized


def _positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 and str(parsed) == str(value).strip() else None


def _lookup_makerspace_id(url_name, pk):
    model_path, field = MODEL_LOOKUPS[url_name]
    model = apps.get_model(model_path)
    try:
        return model.objects.values_list(field, flat=True).get(pk=pk)
    except model.DoesNotExist:
        return None


def _lookup_makerspace_ids(url_name, pk):
    model_path, owner_field, tenant_field = TARGET_SET_LOOKUPS[url_name]
    model = apps.get_model(model_path)
    return set(
        model.objects.filter(**{owner_field: pk})
        .values_list(tenant_field, flat=True)
    )
