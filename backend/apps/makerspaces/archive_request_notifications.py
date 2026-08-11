import logging

from django.db import transaction
from django.urls import reverse

from apps.accounts.models import User
from apps.integrations.dispatch import dispatch_email
from apps.makerspaces.models import MakerspaceArchiveRequest

logger = logging.getLogger(__name__)


def schedule_created(archive_request_id):
    transaction.on_commit(lambda: _send_created(archive_request_id))


def schedule_resolved(archive_request_id):
    transaction.on_commit(lambda: _send_resolved(archive_request_id))


def _send_created(archive_request_id):
    try:
        archive_request = MakerspaceArchiveRequest.objects.select_related(
            "makerspace"
        ).get(pk=archive_request_id)
        review_path = reverse(
            "admin:makerspaces_makerspacearchiverequest_changelist"
        )
        body = (
            f"{archive_request.makerspace.name} has requested archival.\n\n"
            f"Review the request in the control plane: {review_path}?status__exact=pending"
        )
        recipients = User.objects.filter(
            is_active=True,
            is_superuser=True,
            access_status=User.AccessStatus.ACTIVE,
        ).exclude(email="")
        for email in recipients.values_list("email", flat=True):
            email = (email or "").strip()
            if not email:
                continue
            dispatch_email(
                to_email=email,
                subject=f"Archive request: {archive_request.makerspace.name}",
                text_body=body,
                makerspace=None,
                stream="governance",
                event="makerspace_archive_requested",
                audience="superadmin",
                connection="platform",
            )
    except Exception:
        logger.exception(
            "makerspace_archive_request_notification_failed",
            extra={"archive_request_id": archive_request_id},
        )


def _send_resolved(archive_request_id):
    try:
        archive_request = MakerspaceArchiveRequest.objects.select_related(
            "makerspace", "requested_by"
        ).get(pk=archive_request_id)
        requester = archive_request.requested_by
        # Actor attribution survives in the immutable audit log. Email delivery is
        # best-effort because staff identities created without an address are valid.
        if requester is None or not (requester.email or "").strip():
            return
        requester_email = requester.email.strip()
        body = (
            f"Your request to archive {archive_request.makerspace.name} was "
            f"{archive_request.status}."
        )
        if archive_request.resolution_note:
            body = f"{body}\n\nNote: {archive_request.resolution_note}"
        dispatch_email(
            to_email=requester_email,
            subject=(
                f"Archive request {archive_request.status}: "
                f"{archive_request.makerspace.name}"
            ),
            text_body=body,
            makerspace=None,
            stream="governance",
            event="makerspace_archive_request_resolved",
            audience="requester",
            connection="platform",
            persist_body=not bool(archive_request.resolution_note),
            sync=bool(archive_request.resolution_note),
        )
    except Exception:
        logger.exception(
            "makerspace_archive_request_outcome_notification_failed",
            extra={"archive_request_id": archive_request_id},
        )
