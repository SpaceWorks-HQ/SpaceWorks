from django.db.models import (
    BooleanField,
    Case,
    CharField,
    DateTimeField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone as django_timezone

from apps.accounts import rbac
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.hardware_requests.self_checkout_models import PublicToolLoan
from apps.operations.ledger_query_constants import (
    LEDGER_COLUMNS,
    SORT_FIELDS,
    SOURCE_DIRECT,
    SOURCE_QUERY_VALUES,
    SOURCE_REVIEWED,
    SOURCE_SELF_CHECKOUT,
    _CEILING,
    _FLOOR,
)
from apps.operations.ledger_query_filters import (
    _filter_container_rows,
    _filter_item_rows,
    _order_by,
)
def normalize_source(value):
    return SOURCE_QUERY_VALUES.get(value)

def normalize_sort(value):
    raw = (value or "").strip()
    if not raw:
        return None
    field = raw[1:] if raw.startswith("-") else raw
    return raw if field in SORT_FIELDS else None

def ordered_queryset(makerspace_id, *, filters=None):
    filters = filters or {}
    return _ledger_queryset(makerspace_id, filters).order_by(
        *_order_by(filters.get("sort"))
    )

def _ledger_queryset(makerspace_id, filters):
    item_rows = _filter_item_rows(
        _annotated_item_queryset(makerspace_id), filters, makerspace_id
    )
    container_rows = _filter_container_rows(
        _annotated_container_queryset(makerspace_id), filters, makerspace_id
    )
    return item_rows.values(*LEDGER_COLUMNS).union(
        container_rows.values(*LEDGER_COLUMNS),
        all=True,
    )

def _annotated_item_queryset(makerspace_id):
    return _request_item_queryset(makerspace_id).annotate(
        ledger_source=Case(
            When(request__public_tool_loan__isnull=True, then=Value(SOURCE_REVIEWED)),
            When(
                request__public_tool_loan__source=PublicToolLoan.Source.PUBLIC_SELF_CHECKOUT,
                then=Value(SOURCE_SELF_CHECKOUT),
            ),
            default=Value(SOURCE_DIRECT),
            output_field=CharField(),
        ),
        ledger_item_name=F("product__name"),
        ledger_container=Coalesce(
            "request__public_tool_loan__container__label",
            "request__assigned_box__label",
            output_field=CharField(),
        ),
        holder_sort_id=F("request__requester_id"),
        quantity=F("outstanding"),
        ledger_target_label=F("request__public_tool_loan__target_label"),
        since=F("request__issued_at"),
        due=Coalesce(
            "request__public_tool_loan__due_at",
            "request__return_due_at",
            output_field=DateTimeField(),
        ),
        since_sort=Coalesce(
            "request__issued_at", Value(_FLOOR), output_field=DateTimeField()
        ),
        due_sort=Coalesce(
            "request__public_tool_loan__due_at",
            "request__return_due_at",
            Value(_CEILING),
            output_field=DateTimeField(),
        ),
        overdue=Case(
            When(
                Q(request__public_tool_loan__due_at__lt=django_timezone.now())
                | Q(
                    request__public_tool_loan__due_at__isnull=True,
                    request__return_due_at__lt=django_timezone.now(),
                ),
                then=Value(True),
            ),
            default=Value(False),
            output_field=BooleanField(),
        ),
        ledger_makerspace_id=F("request__makerspace_id"),
        reference_id=Coalesce(
            "request__public_tool_loan__id", "request_id", output_field=IntegerField()
        ),
        ledger_status=F("request__status"),
        row_group=Value(0, output_field=IntegerField()),
        ledger_item_id=F("id"),
        ledger_request_id=F("request_id"),
        ledger_product_id=F("product_id"),
        loan_id=F("request__public_tool_loan__id"),
    )

def _annotated_container_queryset(makerspace_id):
    return _container_only_loan_queryset(makerspace_id).annotate(
        ledger_source=Value(SOURCE_DIRECT, output_field=CharField()),
        ledger_item_name=F("container__label"),
        ledger_container=Value(None, output_field=CharField()),
        holder_sort_id=F("request__requester_id"),
        quantity=Value(1, output_field=IntegerField()),
        ledger_target_label=Value(None, output_field=CharField()),
        since=Coalesce("checked_out_at", "request__issued_at", output_field=DateTimeField()),
        due=F("due_at"),
        since_sort=Coalesce(
            "checked_out_at",
            "request__issued_at",
            Value(_FLOOR),
            output_field=DateTimeField(),
        ),
        due_sort=Coalesce("due_at", Value(_CEILING), output_field=DateTimeField()),
        overdue=Case(
            When(due_at__lt=django_timezone.now(), then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        ),
        ledger_makerspace_id=F("makerspace_id"),
        reference_id=F("id"),
        ledger_status=F("request__status"),
        row_group=Value(1, output_field=IntegerField()),
        ledger_request_id=F("request_id"),
        ledger_item_id=Value(None, output_field=IntegerField()),
        ledger_product_id=Value(None, output_field=IntegerField()),
        loan_id=F("id"),
    )

def _request_item_queryset(makerspace_id):
    queryset = (
        HardwareRequestItem.objects.filter(
            request__status__in=[
                HardwareRequest.Status.ISSUED,
                HardwareRequest.Status.PARTIALLY_RETURNED,
            ]
        )
        .annotate(
            outstanding=F("issued_quantity")
            - F("returned_quantity")
            - F("damaged_quantity")
            - F("missing_quantity")
        )
        .filter(outstanding__gt=0)
    )
    if makerspace_id is not None:
        return queryset.filter(request__makerspace_id=makerspace_id)
    excluded = rbac.superadmin_hidden_makerspace_ids() | rbac.archived_makerspace_ids()
    return queryset.exclude(request__makerspace_id__in=excluded) if excluded else queryset

def _container_only_loan_queryset(makerspace_id):
    outstanding_items = (
        HardwareRequestItem.objects.filter(request_id=OuterRef("request_id"))
        .annotate(
            outstanding=F("issued_quantity")
            - F("returned_quantity")
            - F("damaged_quantity")
            - F("missing_quantity")
        )
        .filter(outstanding__gt=0)
    )
    queryset = (
        PublicToolLoan.objects.filter(
            source=PublicToolLoan.Source.ADMIN_DIRECT,
            status=PublicToolLoan.Status.CHECKED_OUT,
            container__isnull=False,
        )
        .annotate(has_outstanding_items=Exists(outstanding_items))
        .filter(has_outstanding_items=False)
    )
    if makerspace_id is not None:
        return queryset.filter(makerspace_id=makerspace_id)
    excluded = rbac.superadmin_hidden_makerspace_ids() | rbac.archived_makerspace_ids()
    return queryset.exclude(makerspace_id__in=excluded) if excluded else queryset
