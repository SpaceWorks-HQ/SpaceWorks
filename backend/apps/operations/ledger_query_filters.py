from django.db.models import Q

from apps.accounts import rbac
from apps.hardware_requests.models import HardwareRequest
from apps.operations.ledger_query_constants import SORT_FIELDS, SOURCE_DIRECT


def _filter_item_rows(queryset, filters, makerspace_id=None):
    queryset = _filter_common(queryset, filters)
    search = (filters.get("search") or "").strip()
    if search:
        queryset = queryset.filter(
            _borrower_search_q("request", search, makerspace_id)
            | Q(product__name__icontains=search)
            | Q(request__assigned_box__label__icontains=search)
            | Q(request__public_tool_loan__container__label__icontains=search)
        )
    return queryset

def _filter_container_rows(queryset, filters, makerspace_id=None):
    source = filters.get("source")
    if source and source != SOURCE_DIRECT:
        queryset = queryset.none()
    queryset = _filter_common(queryset, {**filters, "source": None})
    search = (filters.get("search") or "").strip()
    if search:
        queryset = queryset.filter(
            _borrower_search_q("request", search, makerspace_id)
            | Q(container__label__icontains=search)
        )
    return queryset

def _filter_common(queryset, filters):
    source = filters.get("source")
    if source:
        queryset = queryset.filter(ledger_source=source)
    overdue = filters.get("overdue")
    if overdue is not None:
        queryset = queryset.filter(overdue=overdue)
    return queryset

def _borrower_search_q(prefix, search, makerspace_id=None):
    native = (
        Q(**{f"{prefix}__requester__email__icontains": search})
        | Q(**{f"{prefix}__requester__external_checkin_user_id__icontains": search})
        | Q(**{f"{prefix}__requester__username__icontains": search})
    )
    from django.conf import settings
    if not settings.PII_ENCRYPTION_ENABLED:
        return native | Q(**{f"{prefix}__requester_name__icontains": search}) | Q(**{f"{prefix}__requester_contact_email__icontains": search})
    request_ids = _pii_request_ids(search, makerspace_id)
    if request_ids:
        native = native | Q(**{f"{prefix}__pk__in": request_ids})
    return native


def _pii_request_ids(term, makerspace_id):
    """Resolve HardwareRequest PKs matching the encrypted name/email via blind index.

    Tenant-scoped candidate generation + decrypt-verify, unioned with the sanctioned
    raw legacy-plaintext adapter during the dual-read rollout window.
    """
    from django.conf import settings
    from rest_framework.exceptions import ValidationError

    from apps.encryption.search import (
        indexed_candidates,
        legacy_plaintext_candidates,
        verified_ids,
    )

    label = "hardware_requests.HardwareRequest"
    if makerspace_id is not None:
        space_ids = [makerspace_id]
    else:  # superadmin aggregate: bound to the visible makerspaces owning requests
        excluded = rbac.superadmin_hidden_makerspace_ids() | rbac.archived_makerspace_ids()
        base = HardwareRequest.objects.all()
        if excluded:
            base = base.exclude(makerspace_id__in=excluded)
        space_ids = list(base.values_list("makerspace_id", flat=True).distinct())
    ids = set()
    for ms_id in space_ids:
        scoped = HardwareRequest.objects.filter(makerspace_id=ms_id)
        for field_name, exact in (("requester_name", False), ("requester_contact_email", True)):
            try:
                candidates = indexed_candidates(
                    makerspace_id=ms_id, model_label=label, field_name=field_name,
                    term=term, exact=exact,
                )
            except ValidationError:  # e.g. name term shorter than a trigram
                candidates = []
            ids.update(verified_ids(scoped.filter(pk__in=candidates), field_name=field_name, term=term, exact=exact))
            if settings.PII_ENCRYPTION_DUAL_READ:
                ids.update(legacy_plaintext_candidates(scoped, field_name=field_name, term=term, exact=exact))
    return ids

def _order_by(sort):
    if sort:
        descending = sort.startswith("-")
        field = sort[1:] if descending else sort
        direction = "-" if descending else ""
        return [
            f"{direction}{SORT_FIELDS[field]}",
            "-since_sort",
            "row_group",
            "ledger_request_id",
            "ledger_item_id",
            "loan_id",
        ]
    return ["-since_sort", "row_group", "ledger_request_id", "ledger_item_id", "loan_id"]
