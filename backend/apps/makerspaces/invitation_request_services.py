"""Invitation requests: public submission and the staff invite/decline decisions."""
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.makerspaces import membership_services
from apps.makerspaces.models import InvitationRequest


def submit_invitation_request(makerspace, *, name, email, phone="", message=""):
    with transaction.atomic():
        row = InvitationRequest.objects.create(
            makerspace=makerspace,
            name=name,
            email=membership_services.normalized_email(email),
            phone=phone,
            message=message,
        )
        # Anonymous submitter: the row is the target, the makerspace is the scope.
        audit.record(
            None,
            "invitation_request.submitted",
            makerspace=makerspace,
            target=row,
            meta={"invitation_request_id": row.pk},
        )
    return row


def _lock_pending(row):
    locked = InvitationRequest.objects.select_for_update(of=("self",)).select_related(
        "makerspace"
    ).get(pk=row.pk)
    if locked.status != InvitationRequest.Status.PENDING:
        raise ValidationError({"detail": "This invitation request has already been handled."})
    return locked


def invite_from_request(actor, row, assigned_role):
    """Issue the ordinary membership invitation, then mark the lead as invited."""
    with transaction.atomic():
        row = _lock_pending(row)
        invitation = membership_services.invite_membership(
            actor, row.makerspace, row.email, assigned_role
        )
        row.status = InvitationRequest.Status.INVITED
        row.handled_by = actor
        row.handled_at = timezone.now()
        row.save(update_fields=["status", "handled_by", "handled_at"])
        audit.record(
            actor,
            "invitation_request.invited",
            makerspace=row.makerspace,
            target=row,
            meta={
                "invitation_request_id": row.pk,
                "membership_request_id": invitation.pk,
                "role_id": assigned_role.pk,
            },
        )
    return row


def decline_request(actor, row):
    with transaction.atomic():
        row = _lock_pending(row)
        row.status = InvitationRequest.Status.DECLINED
        row.handled_by = actor
        row.handled_at = timezone.now()
        row.save(update_fields=["status", "handled_by", "handled_at"])
        audit.record(
            actor,
            "invitation_request.declined",
            makerspace=row.makerspace,
            target=row,
            meta={"invitation_request_id": row.pk},
        )
    return row
