import re

from django.db.models import Count, F, Sum
from django.utils import timezone

from apps.hardware_requests.display import is_internal_checkin_username
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.hardware_requests.self_checkout_models import PublicToolLoan
from apps.inventory.models import InventoryProduct, PublicAvailabilityMode


ACTIVE_LOAN_STATUSES = (
    HardwareRequest.Status.ISSUED,
    HardwareRequest.Status.PARTIALLY_RETURNED,
)


def public_display_name(*, request=None, requester=None) -> str:
    candidates = []
    if request is not None:
        label = _safe_public_requester_name(getattr(request, 'requester_name', ''))
        if label:
            return label
        candidates.append(getattr(request, 'requester_username', ''))
        requester = requester or getattr(request, 'requester', None)
    if requester is not None:
        get_full_name = getattr(requester, 'get_full_name', None)
        if callable(get_full_name):
            candidates.append(get_full_name())
        candidates.append(getattr(requester, 'username', ''))

    for value in candidates:
        label = _clean_label(value)
        if _safe_public_name(label):
            return label
    return 'Member'


def hardware_stats(makerspace):
    products = _public_products(makerspace)
    exact_count_products = _public_exact_count_products(products)
    return {
        'most_popular': _most_popular(makerspace),
        'tools_out': [
            {'name': product.name, 'quantity_out': product.issued_quantity}
            for product in exact_count_products.filter(issued_quantity__gt=0).order_by(
                'name', 'id'
            )
        ],
        'library': _library_counts(products, exact_count_products),
        'recently_added': _recently_added(products),
    }


def _most_popular(makerspace):
    rows = (
        HardwareRequestItem.objects.filter(
            request__makerspace=makerspace,
            product__is_public=True,
            product__is_archived=False,
            issued_quantity__gt=0,
        )
        .values('product_id', 'product__name')
        .annotate(
            times_lent=Count('request_id', distinct=True),
            total_quantity_lent=Sum('issued_quantity'),
        )
        .order_by('-times_lent', '-total_quantity_lent', 'product__name', 'product_id')
    )
    return [
        {
            'name': row['product__name'],
            'times_lent': row['times_lent'],
            'total_quantity_lent': row['total_quantity_lent'] or 0,
        }
        for row in rows
    ]


def _library_counts(products, exact_count_products):
    totals = exact_count_products.aggregate(
        currently_out_count=Sum('issued_quantity'),
        available_count=Sum('available_quantity'),
    )
    return {
        'currently_out_count': totals['currently_out_count'] or 0,
        'library_size': products.count(),
        'available_count': totals['available_count'] or 0,
    }


def _recently_added(products):
    start, end = _current_month_window()
    return [
        {'name': product.name, 'created_at': product.created_at}
        for product in products.filter(created_at__gte=start, created_at__lt=end).order_by(
            '-created_at', '-id'
        )
    ]


def current_loans(makerspace):
    queryset = (
        HardwareRequestItem.objects.select_related(
            'product',
            'request',
            'request__requester',
            'request__public_tool_loan',
            'request__public_tool_loan__requester',
        )
        .filter(
            request__makerspace=makerspace,
            request__status__in=ACTIVE_LOAN_STATUSES,
            product__is_public=True,
            product__is_archived=False,
        )
        .exclude(product__public_availability_mode=PublicAvailabilityMode.HIDDEN)
        .annotate(
            outstanding=(
                F('issued_quantity')
                - F('returned_quantity')
                - F('damaged_quantity')
                - F('missing_quantity')
            )
        )
        .filter(outstanding__gt=0)
        .order_by('-request__issued_at', 'request_id', 'id')
    )
    rows = []
    for item in queryset:
        loan = _public_tool_loan(item.request)
        holder_name = 'Member'
        if makerspace.public_stats_show_holder_names:
            holder_name = public_display_name(
                request=item.request,
                requester=(loan.requester if loan else item.request.requester),
            )
        # "Member" removes the directly searchable identifier, but exact due/since
        # timestamps can still let an observer who was present correlate a member
        # with an item. Coarsening dates or suppressing current loans is a broader
        # policy decision not taken here.
        rows.append(
            {
                'item_name': item.product.name,
                'holder_name': holder_name,
                'due': (loan.due_at if loan else None) or item.request.return_due_at,
                'since': (loan.checked_out_at if loan else None) or item.request.issued_at,
            }
        )
    return rows


def _public_products(makerspace):
    return InventoryProduct.objects.filter(
        makerspace=makerspace,
        is_public=True,
        is_archived=False,
    )


def _public_exact_count_products(products):
    return products.filter(
        public_availability_mode=PublicAvailabilityMode.EXACT_COUNT,
        show_public_count=True,
    )


def _public_tool_loan(request):
    try:
        loan = request.public_tool_loan
    except PublicToolLoan.DoesNotExist:
        return None
    return loan if loan.status == PublicToolLoan.Status.CHECKED_OUT else None


def _current_month_window():
    now = timezone.localtime(timezone.now())
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _clean_label(value):
    return str(value or '').strip()


def _safe_public_name(value):
    if not value or '@' in value or _is_internal_checkin_label(value):
        return False
    return len(re.sub(r'\D', '', value)) < 7


def _safe_public_requester_name(value):
    label = ''.join(char for char in _clean_label(value) if char.isprintable()).strip()
    if not _has_visible_text(label) or not _safe_public_name(label):
        return ''
    return label[:60]


def _has_visible_text(value):
    return any(not char.isspace() and char.isprintable() for char in value)


def _is_internal_checkin_label(value):
    return value.lower().startswith('checkin_') or is_internal_checkin_username(value)
