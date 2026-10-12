"""Borrow-limit quantity math, kept in the Inventory Availability module."""

from django.db.models import F, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.makerspaces.models import MembershipTerm
from apps.makerspaces.models_loan_policy import MakerspaceLoanPolicy
from apps.makerspaces.platform import feature_enabled, module_enabled


def enforce_borrow_limits(makerspace, borrower, incoming_quantity):
    """Call under the tenant row lock before creating/issuing a loan.

    Pending requests do not occupy a loan slot. Submission checks are advisory;
    issue/checkout/handout checks enforce the current ceiling at the actual handover.
    """
    if not feature_enabled(makerspace, "loans.limits"):
        return
    policy = MakerspaceLoanPolicy.for_makerspace(makerspace)
    max_active, max_items = policy.loan_max_active, policy.loan_max_items
    if module_enabled(makerspace, "membership"):
        terms = rbac.scope_by_borrower(
            borrower, MembershipTerm.objects.select_related("plan"), makerspace=makerspace,
            owner_field="membership__user", field="membership__makerspace_id",
        ).filter(status="active", starts_at__lte=timezone.now(), ends_at__gt=timezone.now()).order_by("-ends_at", "-pk")
        term = terms.first()
        if term:
            if term.plan.loan_max_active is not None:
                max_active = term.plan.loan_max_active
            if term.plan.loan_max_items is not None:
                max_items = term.plan.loan_max_items
    active = rbac.scope_by_borrower(borrower, HardwareRequest.objects.all(), makerspace=makerspace).filter(
        status__in=[HardwareRequest.Status.ISSUED, HardwareRequest.Status.PARTIALLY_RETURNED],
    )
    if max_active and active.count() >= max_active:
        raise ValidationError({"code": "loan_limit", "detail": "The borrower has reached the active-loan limit."})
    items = rbac.scope_by_borrower(
        borrower, HardwareRequestItem.objects.all(), makerspace=makerspace,
        field="request__makerspace_id", owner_field="request__requester",
    ).filter(request__in=active)
    outstanding = items.aggregate(total=Sum(
        F("issued_quantity") - F("returned_quantity") - F("damaged_quantity") - F("missing_quantity"),
    ))["total"] or 0
    if max_items and outstanding + incoming_quantity > max_items:
        raise ValidationError({"code": "item_limit", "detail": "This handover exceeds the borrower item limit."})


def enforce_request_borrow_limits(request, rejects_by_item=None):
    rejects_by_item = rejects_by_item or {}
    quantity = sum(item.accepted_quantity - rejects_by_item.get(item.pk, (0,))[0]
                   for item in request.items.all())
    enforce_borrow_limits(request.makerspace, request.requester, quantity)


def enforce_product_borrow_limits(makerspace, borrower, product_quantities):
    enforce_borrow_limits(makerspace, borrower, sum(product_quantities.values()))


def enforce_submission_borrow_limits(makerspace, borrower, items):
    enforce_borrow_limits(makerspace, borrower, sum(item["quantity"] for item in items))


def outstanding_request_items(queryset):
    return queryset.filter(issued_quantity__gt=(
        F("returned_quantity") + F("damaged_quantity") + F("missing_quantity")
    ))
