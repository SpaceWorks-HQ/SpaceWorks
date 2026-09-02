from datetime import datetime, time, timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.operations import reports
from apps.operations.report_registry import REPORT_DEFINITIONS


def _require_source_modules(makerspace, modules):
    for module in modules:
        require_module(makerspace, module)


def _date_range(request):
    start = _date_param(request, "start")
    end = _date_param(request, "end")
    if start and end and start > end:
        raise ValidationError({"end": "End date must be on or after start date."})
    start_dt = timezone.make_aware(datetime.combine(start, time.min)) if start else None
    end_dt = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min)) if end else None
    return (start_dt, end_dt) if start_dt or end_dt else None


def _date_param(request, name):
    raw = (request.query_params.get(name) or "").strip()
    if not raw:
        return None
    parsed = parse_date(raw)
    if parsed is None:
        raise ValidationError({name: "Use YYYY-MM-DD."})
    return parsed


def _makerspace_for_inventory_view(user, makerspace_id):
    queryset = rbac.scope_by_action(
        user, rbac.Action.VIEW_INVENTORY, Makerspace.objects.all(), field="id"
    )
    queryset = rbac.hide_from_superadmin(user, queryset, field="id")
    return get_object_or_404(queryset, pk=makerspace_id)


def _makerspace_for_catalog(user, makerspace_id):
    queryset = Makerspace.objects.none()
    for action in {definition.required_action for definition in REPORT_DEFINITIONS}:
        queryset = queryset | rbac.scope_by_action(
            user, action, Makerspace.objects.all(), field="id"
        )
    queryset = rbac.hide_from_superadmin(user, queryset, field="id")
    return get_object_or_404(queryset.distinct(), pk=makerspace_id)


def _require_superadmin(user):
    if not (user.is_superuser or user.role == user.Role.SUPERADMIN):
        raise PermissionDenied()


def _positive_int_param(request, name, default, maximum):
    raw = request.query_params.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: "Enter a positive integer."}) from exc
    if value < 1:
        raise ValidationError({name: "Enter a positive integer."})
    return min(value, maximum)


def _page_params(request):
    return (
        _positive_int_param(request, "page", 1, 1000000),
        _positive_int_param(request, "page_size", 100, 500),
    )


def _limit_param(request):
    return _positive_int_param(
        request, "limit", reports.DEFAULT_REPORT_LIMIT, reports.MAX_REPORT_LIMIT
    )
