from decimal import Decimal, ROUND_HALF_UP
import secrets

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.events.invites import code_digest, require_feature
from apps.events.models import EventPromoCode
from apps.events.services import _audit, _locked_event
from apps.makerspaces.guards import require_module_locked


@transaction.atomic
def create_promo(event, *, actor, code="", percent_off=0, amount_off=0, max_uses=1, expires_at=None):
    event = _locked_event(event.pk)
    event.makerspace = require_module_locked(event.makerspace, "events")
    require_feature(event, "events.promo_codes")
    amount_off = Decimal(str(amount_off))
    if not (0 <= percent_off <= 100) or amount_off < 0 or bool(percent_off) == bool(amount_off):
        raise ValidationError("Choose one positive percentage or amount discount.")
    if max_uses < 1 or (expires_at and expires_at <= timezone.now()):
        raise ValidationError("Use a positive limit and future expiry.")
    code = code.strip() or secrets.token_urlsafe(24)
    digest = code_digest(code, "promo")
    if EventPromoCode.objects.filter(event=event, code_digest=digest).exists():
        raise ValidationError({"code": "Code is unavailable."})
    promo = EventPromoCode.objects.create(
        event=event, makerspace=event.makerspace, code_digest=digest,
        percent_off=percent_off, amount_off=amount_off, max_uses=max_uses, expires_at=expires_at,
    )
    _audit(event, actor, "event.promo_created", promo)
    return promo, code


def redeem_promo(event, code, amount):
    require_feature(event, "events.promo_codes")
    promo = EventPromoCode.objects.select_for_update().filter(
        event=event, makerspace=event.makerspace, code_digest=code_digest(code, "promo"),
    ).first()
    if not promo or promo.revoked_at or promo.uses >= promo.max_uses or (
        promo.expires_at and promo.expires_at <= timezone.now()
    ):
        raise NotFound("Promo code not found.")
    discount = amount * Decimal(promo.percent_off) / 100 if promo.percent_off else promo.amount_off
    discount = min(amount, discount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    promo.uses += 1
    promo.save(update_fields=["uses"])
    return promo, discount


@transaction.atomic
def revoke_promo(promo, *, actor):
    event = _locked_event(promo.event_id)
    event.makerspace = require_module_locked(event.makerspace, "events")
    require_feature(event, "events.promo_codes")
    locked = EventPromoCode.objects.select_for_update().get(pk=promo.pk, event=event)
    if not locked.revoked_at:
        locked.revoked_at = timezone.now()
        locked.save(update_fields=["revoked_at"])
        _audit(event, actor, "event.promo_revoked", locked)
    return locked
