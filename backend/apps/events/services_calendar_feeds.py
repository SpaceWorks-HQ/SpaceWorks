import hashlib
import hmac
import re
import secrets

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.events.models import MemberCalendarFeed
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.models import MakerspaceMembership


def token_digest(raw_token):
    return hashlib.sha256(raw_token.encode("ascii")).digest()


def feed_state(membership):
    feed = MemberCalendarFeed.objects.filter(membership=membership).first()
    if feed is None or feed.revoked_at is not None:
        return {"enabled": False, "token_hint": None, "created_at": None, "rotated_at": None}
    return {
        "enabled": True,
        "token_hint": feed.token_hint,
        "created_at": feed.created_at,
        "rotated_at": feed.rotated_at,
    }


@transaction.atomic
def issue_or_rotate_feed(membership, *, actor):
    locked_membership = MakerspaceMembership.objects.select_for_update().get(pk=membership.pk)
    if locked_membership.status != "active":
        raise PermissionError("Active membership is required.")
    require_module_locked(locked_membership.makerspace_id, "events")
    feed = MemberCalendarFeed.objects.select_for_update().filter(
        membership=locked_membership
    ).first()
    raw_token = secrets.token_urlsafe(32)
    digest = token_digest(raw_token)
    hint = raw_token[-8:]
    now = timezone.now()
    if feed is None:
        feed = MemberCalendarFeed.objects.create(
            membership=locked_membership, token_digest=digest, token_hint=hint
        )
        action = "event.calendar_feed_created"
    else:
        feed.token_digest = digest
        feed.token_hint = hint
        feed.rotated_at = now
        feed.revoked_at = None
        feed.save(update_fields=("token_digest", "token_hint", "rotated_at", "revoked_at"))
        action = "event.calendar_feed_rotated"
    audit.record(
        actor, action, makerspace=locked_membership.makerspace, target=feed,
        meta={"membership_id": locked_membership.pk},
    )
    return feed, raw_token


@transaction.atomic
def revoke_feed(membership, *, actor):
    locked_membership = MakerspaceMembership.objects.select_for_update().get(pk=membership.pk)
    require_module_locked(locked_membership.makerspace_id, "events")
    feed = MemberCalendarFeed.objects.select_for_update().filter(
        membership=locked_membership, revoked_at__isnull=True
    ).first()
    if feed is None:
        return False
    feed.revoked_at = timezone.now()
    feed.save(update_fields=("revoked_at",))
    audit.record(
        actor, "event.calendar_feed_revoked", makerspace=locked_membership.makerspace,
        target=feed, meta={"membership_id": locked_membership.pk},
    )
    return True


def resolve_feed(raw_token):
    # token_urlsafe(32) is exactly 43 base64url characters. Reject malformed values
    # before hashing so arbitrary Unicode paths cannot become a 500/error oracle.
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", raw_token or ""):
        return None
    digest = token_digest(raw_token)
    feed = MemberCalendarFeed.objects.select_related(
        "membership__makerspace", "membership__user"
    ).filter(token_digest=digest, revoked_at__isnull=True).first()
    if feed is None or not hmac.compare_digest(bytes(feed.token_digest), digest):
        return None
    return feed
