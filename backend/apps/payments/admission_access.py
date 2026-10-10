"""A rejoining applicant may pay their approved admission, without old debt access."""

from django.db.models import F
from django.utils import timezone

from apps.makerspaces.models import Makerspace, MakerspaceMembership, MembershipRequest
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.servability import servable_queryset
from apps.payments.models import Payment


def admission_payment_queryset(user, makerspace_id):
    if not (
        user and user.is_authenticated and user.pk and user.is_active
        and user.access_status == user.AccessStatus.ACTIVE
        and getattr(user, "_claim_audit_context", None) is None
    ):
        return Payment.objects.none()
    makerspace = servable_queryset(Makerspace.objects.filter(pk=makerspace_id)).first()
    if makerspace is None or not module_enabled(makerspace, "membership"):
        return Payment.objects.none()
    requests = MembershipRequest.objects.filter(
        makerspace_id=makerspace_id, user=user, admission_managed=True,
        state="awaiting_payment", approved_at__isnull=False, expires_at__gt=timezone.now(),
        admission_payment__makerspace_id=makerspace_id,
        admission_payment__member=user, admission_payment__subject_id=F("pk"),
        admission_payment__subject_type=Payment.SubjectType.MEMBERSHIP_REQUEST,
        admission_payment__status=Payment.Status.PENDING,
    )
    return Payment.objects.filter(
        pk__in=requests.values("admission_payment_id"), member=user,
        makerspace_id=makerspace_id, subject_type=Payment.SubjectType.MEMBERSHIP_REQUEST,
        status=Payment.Status.PENDING,
    )


def restrict_revoked_debts(queryset, user, makerspace_id):
    # Archived discovery builds a correlated subquery under the canonical ACTIVE
    # membership predicate. Only concrete HTTP/member-area scopes need this check.
    if not isinstance(makerspace_id, (int, str)):
        return queryset
    if MakerspaceMembership.objects.filter(
        user=user, makerspace_id=makerspace_id,
    ).exclude(status="active").exists():
        return queryset.filter(pk__in=admission_payment_queryset(user, makerspace_id).values("pk"))
    return queryset
