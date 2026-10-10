"""Send once without persisting a live bearer in delivery logs; link always recoverable."""

import logging
from urllib.parse import urlencode

from django.conf import settings

from apps.integrations.dispatch import dispatch_email
from apps.makerspaces.models import Makerspace

logger = logging.getLogger(__name__)


def deliver(invitation, raw):
    space = invitation.makerspace
    base = (settings.PUBLIC_APP_BASE_URL or "").rstrip("/")
    if space.frontend_domain and space.frontend_domain_status == Makerspace.DomainStatus.VERIFIED:
        base = f"https://{space.frontend_domain}"
    # Fragment keeps the bearer out of HTTP access logs and Referer headers.
    link = f"{base}/staff-invitations/accept#{urlencode({'token': raw, 'space': space.slug})}"
    status = "unavailable"
    try:
        log = dispatch_email(
            to_email=invitation.email, subject=f"Staff invitation to {space.name}",
            text_body=f"You have been invited as {invitation.role.name} at {space.name}.\n"
                      f"Accept: {link}\nExpires: {invitation.expires_at.isoformat()}.\n"
                      "If you already have an account, use its existing password. "
                      "If you did not expect this invitation, ignore it.",
            makerspace=space, stream="account", event="staff_invitation", audience="staff",
            persist_body=False, sync=True,
        )
        status = log.status
    except Exception:
        # No exception text or traceback: provider failures can carry credentials.
        logger.warning("staff_invitation_delivery_failed", extra={"invitation_id": invitation.pk})
    return {"accept_url": link, "delivery_status": status}
