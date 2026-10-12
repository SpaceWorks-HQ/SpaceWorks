"""Ownership checks for admission charges, including preserved orphan receipts."""

from django.core.exceptions import ValidationError


def validate_membership_request(payment, identity_unchanged):
    from apps.makerspaces.models import MembershipRequest

    request = MembershipRequest.objects.filter(
        pk=payment.subject_id, makerspace_id=payment.makerspace_id,
    ).only("user_id").first()
    if request is None and not identity_unchanged:
        raise ValidationError({
            "subject_id": "Payment subject must belong to the payment makerspace.",
        })
    if request is not None and (request.user_id is None or payment.member_id != request.user_id):
        raise ValidationError({"member": "Payment member must be the applicant."})
