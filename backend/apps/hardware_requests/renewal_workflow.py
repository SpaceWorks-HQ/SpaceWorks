"""Policy-bound extensions, exposed through the request workflow barrel."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit import services as audit
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem, PublicToolLoan
from apps.inventory import availability
from apps.makerspaces.guards import require_feature_locked, require_module
from apps.makerspaces.loan_policy import renewal_cap
from apps.makerspaces.models import MakerspaceMembership, MembershipTerm
from apps.makerspaces.models_loan_policy import MakerspaceLoanPolicy

ACTIVE_LOAN_STATUSES = (HardwareRequest.Status.ISSUED, HardwareRequest.Status.PARTIALLY_RETURNED)


def _refuse(code, detail):
    raise ValidationError({"code": code, "detail": detail})


def check_renewal(loan, policy, *, actor=None, staff=False):
    """Read-only eligibility, reused by the member UI and the locked mutation."""
    if loan.status not in ACTIVE_LOAN_STATUSES or loan.return_due_at is None:
        _refuse("loan_not_active", "Only an issued loan with a due date can be renewed.")
    if policy.loan_renewal_mode != MakerspaceLoanPolicy.RenewalMode.AUTO:
        _refuse("renewals_off", "Automatic loan renewals are disabled.")
    actor = actor or loan.requester
    def scoped(queryset, field="makerspace_id"):
        if staff:
            return rbac.scope_by_action(actor, rbac.Action.ACCEPT_REQUEST, queryset, field=field)
        return rbac.scope_by_makerspace(actor, queryset, makerspace_field=field)

    borrower = loan.requester
    if not borrower.is_active or borrower.access_status != User.AccessStatus.ACTIVE:
        _refuse("borrower_restricted", "The borrower is inactive or restricted.")
    memberships = scoped(MakerspaceMembership.objects.all()).filter(
        makerspace_id=loan.makerspace_id, user=borrower,
    )
    membership = memberships.first()
    if membership is not None and membership.status != "active":
        _refuse("membership_inactive", "The borrower membership is inactive.")
    from apps.makerspaces.platform import module_enabled

    if module_enabled(loan.makerspace, "membership"):
        if membership is None:
            _refuse("membership_required", "An active borrower membership is required.")
        terms = scoped(MembershipTerm.objects.all(), field="membership__makerspace_id").filter(membership=membership)
        if terms.exists() and not terms.filter(status="active", starts_at__lte=timezone.now(), ends_at__gt=timezone.now()).exists():
            _refuse("membership_lapsed", "Renew your membership before extending this loan.")
    items = scoped(HardwareRequestItem.objects.select_related("product__category"),
                   field="request__makerspace_id").filter(request=loan)
    products = [item.product for item in availability.outstanding_request_items(items)]
    if loan.renewal_count >= renewal_cap(policy, products):
        _refuse("renewal_limit", "This loan has reached its renewal limit.")
    waiting = scoped(HardwareRequest.objects.all()).filter(
        Q(status=HardwareRequest.Status.PENDING_APPROVAL)
        | Q(status=HardwareRequest.Status.ACCEPTED, items__accepted_quantity__gt=0),
        makerspace_id=loan.makerspace_id,
        items__product_id__in=[product.pk for product in products],
    ).exclude(requester=borrower)
    if waiting.exists():
        _refuse("request_waiting", "Another borrower is waiting for an item in this loan.")


def renew_loan(actor, request, *, staff=False):
    if not (actor and actor.is_authenticated and actor.is_active
            and actor.access_status == User.AccessStatus.ACTIVE
            and not actor.is_tenant_dump_stub
            and not getattr(actor, "must_change_password", False)):
        raise PermissionDenied("An active, unrestricted actor is required to renew a loan.")
    with transaction.atomic():
        # Settings updates use the same tenant lock, so disabling renewals wins cleanly.
        makerspace = require_feature_locked(request.makerspace_id, "loans.renewals")
        require_module(makerspace, "request_workflow")
        if staff:
            scoped = rbac.scope_by_action(actor, rbac.Action.ACCEPT_REQUEST, HardwareRequest.objects.all())
        else:
            require_module(makerspace, "membership")
            scoped = rbac.scope_by_makerspace(actor, HardwareRequest.objects.all()).filter(requester=actor)
        loan = scoped.select_for_update().filter(pk=request.pk, makerspace=makerspace).first()
        if loan is None:
            raise PermissionDenied("This loan is outside your renewal scope.")
        loan.makerspace = makerspace
        policy = MakerspaceLoanPolicy.for_makerspace(makerspace)
        check_renewal(loan, policy, actor=actor, staff=staff)
        old_due = loan.return_due_at
        # Extend from the contractual due instant; late-fee grace uses the new due date.
        try:
            loan.return_due_at = old_due + timedelta(days=policy.loan_renewal_days)
        except OverflowError:
            _refuse("due_date_out_of_range", "The renewed due date exceeds the supported range.")
        loan.renewal_count += 1
        loan.return_reminder_sent_at = None
        loan.save(update_fields=["return_due_at", "renewal_count", "return_reminder_sent_at", "updated_at"])
        linked = rbac.scope_by_action(actor, rbac.Action.ACCEPT_REQUEST, PublicToolLoan.objects.all()) if staff else rbac.scope_by_makerspace(actor, PublicToolLoan.objects.all())
        linked.filter(makerspace=makerspace, request=loan, status=PublicToolLoan.Status.CHECKED_OUT).update(due_at=loan.return_due_at)
        audit.record(actor, "request.renewed", makerspace=makerspace, target=loan, meta={
            "old_return_due_at": old_due.isoformat(), "return_due_at": loan.return_due_at.isoformat(),
            "renewal_count": loan.renewal_count, "staff": staff,
        })
        return loan
