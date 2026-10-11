"""Codes are scoped to one event and consumed inside its registration transaction."""

import hashlib
import hmac
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.events.models import EventInvite
from apps.events.services import _audit, _locked_event
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.platform import feature_enabled


def code_digest(value, purpose):
    message = f"events:{purpose}:{str(value).strip().lower()}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def require_feature(event, key):
    if not feature_enabled(event.makerspace, key):
        raise ValidationError({"detail": "This events feature is disabled."})


@transaction.atomic
def create_invite(event, *, actor, email="", max_uses=1, expires_at=None):
    event = _locked_event(event.pk)
    event.makerspace = require_module_locked(event.makerspace, "events")
    require_feature(event, "events.invites")
    if max_uses < 1 or (expires_at and expires_at <= timezone.now()):
        raise ValidationError("Use a positive limit and future expiry.")
    code = secrets.token_urlsafe(32)
    invite = EventInvite.objects.create(
        event=event, makerspace=event.makerspace, code_digest=code_digest(code, "invite"),
        email_digest=code_digest(email, "email") if email else "",
        max_uses=max_uses, expires_at=expires_at,
    )
    _audit(event, actor, "event.invite_created", invite)
    return invite, code


def redeem_invite(event, code, member):
    require_feature(event, "events.invites")
    invite = EventInvite.objects.select_for_update().filter(
        event=event, makerspace=event.makerspace, code_digest=code_digest(code or "", "invite"),
    ).first()
    if not invite or invite.revoked_at or invite.uses >= invite.max_uses or (
        invite.expires_at and invite.expires_at <= timezone.now()
    ) or (invite.email_digest and (not member or not member.email or not hmac.compare_digest(
        invite.email_digest, code_digest(member.email, "email")
    ))):
        raise NotFound("Invitation not found.")
    invite.uses += 1
    invite.save(update_fields=["uses"])
    return invite


@transaction.atomic
def revoke_invite(invite, *, actor):
    event = _locked_event(invite.event_id)
    event.makerspace = require_module_locked(event.makerspace, "events")
    require_feature(event, "events.invites")
    locked = EventInvite.objects.select_for_update().get(pk=invite.pk, event=event)
    if not locked.revoked_at:
        locked.revoked_at = timezone.now()
        locked.save(update_fields=["revoked_at"])
        _audit(event, actor, "event.invite_revoked", locked)
    return locked
