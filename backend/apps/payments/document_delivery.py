"""Fail-safe payer-only mail; download grants remain short-lived and user-bound."""

import logging
from urllib.parse import urlencode

from django.core import signing
from django.urls import reverse

logger = logging.getLogger(__name__)
DOWNLOAD_TTL = 300
SALT = "payments.document.download.v1"


def download_path(document, user, *, makerspace_id, audience):
    token = signing.dumps({"document": document.pk, "user": user.pk,
                           "space": makerspace_id, "audience": audience}, salt=SALT)
    return reverse("payment-document-download", args=[document.pk]) + "?" + urlencode({"token": token})


def email_document(document_id):
    """No arbitrary recipient is accepted; contact is read from the payment owner."""
    from apps.integrations.dispatch import dispatch_email
    from apps.makerspaces.platform import member_payment_return_url
    from apps.payments.models import PaymentDocument

    try:
        document = PaymentDocument.objects.select_related("payment__member", "makerspace").get(pk=document_id)
        payer = document.payment.member
        if payer is None or not payer.email:
            return
        # A durable authenticated member page avoids mailing an already-expired grant.
        # The payer requests a fresh five-minute download URL from that page.
        dispatch_email(
            to_email=payer.email, subject=f"{document.get_kind_display()} {document.number}",
            text_body=(f"Your {document.get_kind_display().lower()} {document.number} is available.\n"
                       f"{document.currency.upper()} {document.amount}\n"
                       f"Sign in to download the PDF: {member_payment_return_url(document.makerspace)}"),
            makerspace=document.makerspace, stream="payments", event="document_issued",
            audience="requester", sync=True, persist_body=False,
        )
    except Exception:
        # Identifiers only: SMTP errors may contain recipient addresses or credentials.
        logger.warning("payment_document_email_failed", extra={"document_id": document_id})
