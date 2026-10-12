"""Bounded pagination and allowlisted, stable ordering for staff lists."""

from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.filters import BaseFilterBackend, OrderingFilter


class StaffListPagination(PageNumberPagination):
    page_size = 24


def identity_filter(params):
    raw = params.get("id", "")
    if not raw:
        return None
    field = serializers.IntegerField(min_value=1, max_value=9223372036854775807)
    try:
        return field.run_validation(raw)
    except serializers.ValidationError as exc:
        raise ValidationError({"id": exc.detail}) from exc


class ListIdentityFilter(BaseFilterBackend):
    """Select a palette hit after the view has applied its tenant/action scope."""
    def filter_queryset(self, request, queryset, view):
        selected_id = identity_filter(request.query_params)
        return queryset.filter(pk=selected_id) if selected_id is not None else queryset

    def get_schema_operation_parameters(self, view):
        return [{"name": "id", "in": "query", "required": False,
                 "description": "Select one result within the authorized list.",
                 "schema": {"type": "integer", "minimum": 1, "maximum": 9223372036854775807}}]


class StableOrderingFilter(OrderingFilter):
    def filter_queryset(self, request, queryset, view):
        raw = request.query_params.get(self.ordering_param, "")
        valid = {name for name, _label in self.get_valid_fields(queryset, view, {"request": request})}
        if raw and any(field.strip().removeprefix("-") not in valid for field in raw.split(",")):
            raise ValidationError({"ordering": "Unsupported sort field."})
        ordering = self.get_ordering(request, queryset, view)
        if ordering:
            return queryset.order_by(*ordering, "pk")
        return queryset.order_by(*queryset.query.order_by, "pk")


LIST_PARAMETERS = [
    OpenApiParameter("page", int, description="Page number, 24 rows per page."),
    OpenApiParameter("ordering", str, description="Allowlisted sort field; prefix with '-' for descending."),
    OpenApiParameter("q", str, description="Search within the authorized list."),
]
ORDER_PAGE_PARAMETERS = LIST_PARAMETERS[:2]


def order_list(queryset, params, allowed, default):
    ordering = params.get("ordering", "") or default
    if ordering.removeprefix("-") not in allowed:
        raise ValidationError({"ordering": "Unsupported sort field."})
    return queryset.order_by(ordering, "pk")


def choice_filter(params, name, choices):
    value = params.get(name, "")
    if value and value not in choices:
        raise ValidationError({name: "Unsupported filter value."})
    return value
