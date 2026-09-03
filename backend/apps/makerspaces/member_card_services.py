"""Issue, reissue, revoke, redact and resolve member ID cards.

Every mutation is audited and every lookup writes an immutable `QrScanEvent` with the
`member_lookup` context. Authority is by ACTION (`MANAGE_MEMBER_CARDS` / `SCAN_MEMBER_CARDS`),
never by role name, and a card never resolves through the generic inventory scanner.
"""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.http import Http404
from django.utils import timezone

from apps.accounts import rbac
from apps.audit import services as audit
from apps.boxes.models import QrCode, QrScanEvent
from apps.boxes.services import revoke_qr_code
from apps.makerspaces import member_card_storage
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.models import MakerspaceMembership, MemberCard

REISSUE_REASONS = ("lost", "stolen", "damaged", "renewed")


def _require(actor, action, makerspace_id):
    if not rbac.can(actor, action, makerspace_id):
        raise PermissionDenied()


def active_qr(card):
    return QrCode.objects.filter(
        makerspace_id=card.makerspace_id,
        target_type=QrCode.TargetType.MEMBER_CARD,
        target_id=card.pk,
        status=QrCode.Status.ACTIVE,
    ).first()


def _next_card_number(makerspace_id):
    current = MemberCard.objects.filter(makerspace_id=makerspace_id).aggregate(
        top=Max("card_number")
    )["top"]
    return (current or 0) + 1


@transaction.atomic
def issue_card(actor, membership, *, printed_name=""):
    _require(actor, rbac.Action.MANAGE_MEMBER_CARDS, membership.makerspace_id)
    require_module_locked(membership.makerspace_id, "membership")
    membership = MakerspaceMembership.objects.select_for_update().get(pk=membership.pk)
    if membership.status != "active":
        raise PermissionDenied("Only an active membership can hold a card.")
    if MemberCard.objects.filter(membership=membership).exists():
        raise PermissionDenied("This membership already holds a card; reissue it instead.")
    card = MemberCard.objects.create(
        makerspace_id=membership.makerspace_id,
        membership=membership,
        card_number=_next_card_number(membership.makerspace_id),
        printed_name=printed_name or "",
    )
    QrCode.objects.create(
        makerspace_id=card.makerspace_id,
        target_type=QrCode.TargetType.MEMBER_CARD,
        target_id=card.pk,
        created_by=actor,
    )
    audit.record(actor, "member_card.created", makerspace=membership.makerspace, target=card, meta={"card_id": card.pk, "card_number": card.card_number})
    audit.record(actor, "member_card.issued", makerspace=membership.makerspace, target=card, meta={"card_id": card.pk, "card_number": card.card_number})
    return card


@transaction.atomic
def reissue_card(actor, card, *, reason):
    """Rotate the QR: the old payload keeps resolving as REVOKED and stays in scan history."""
    _require(actor, rbac.Action.MANAGE_MEMBER_CARDS, card.makerspace_id)
    if reason not in REISSUE_REASONS:
        raise PermissionDenied("Unknown reissue reason.")
    card = MemberCard.objects.select_for_update().get(pk=card.pk)
    if not card.is_active:
        raise PermissionDenied("A revoked card cannot be reissued; issue a new one.")
    old = active_qr(card)
    if old is not None:
        revoke_qr_code(actor, old)
    QrCode.objects.create(
        makerspace_id=card.makerspace_id,
        target_type=QrCode.TargetType.MEMBER_CARD,
        target_id=card.pk,
        created_by=actor,
    )
    card.template_version_at_issue += 1
    card.issued_at = timezone.now()
    card.save(update_fields=["template_version_at_issue", "issued_at", "updated_at"])
    audit.record(actor, "member_card.reissued", makerspace=card.makerspace, target=card, meta={"card_id": card.pk, "card_number": card.card_number, "reason": reason})
    return card


def redact(card):
    """Delete the face photo and blank the name. Idempotent; used on revoke and purge."""
    if card.photo_object_key:
        member_card_storage.delete_photo(card)
    card.printed_name = ""
    card.photo_object_key = ""
    card.photo_content_type = ""
    card.photo_size_bytes = None
    card.photo_consent_at = None
    card.photo_consent_version = ""
    card.save(
        update_fields=[
            "printed_name", "photo_object_key", "photo_content_type", "photo_size_bytes",
            "photo_consent_at", "photo_consent_version", "updated_at",
        ]
    )


@transaction.atomic
def revoke_card(actor, card, *, reason="revoked"):
    _require(actor, rbac.Action.MANAGE_MEMBER_CARDS, card.makerspace_id)
    card = MemberCard.objects.select_for_update().get(pk=card.pk)
    if card.revoked_at is not None:
        return card
    qr = active_qr(card)
    if qr is not None:
        revoke_qr_code(actor, qr)
    card.revoked_at = timezone.now()
    card.revoked_reason = reason[:32]
    card.save(update_fields=["revoked_at", "revoked_reason", "updated_at"])
    redact(card)
    audit.record(actor, "member_card.revoked", makerspace=card.makerspace, target=card, meta={"card_id": card.pk, "card_number": card.card_number, "reason": reason})
    return card


def record_print(actor, cards):
    now = timezone.now()
    for card in cards:
        card.print_count += 1
        card.last_printed_at = now
        card.save(update_fields=["print_count", "last_printed_at", "updated_at"])
        audit.record(actor, "member_card.printed", makerspace=card.makerspace, target=card, meta={"card_id": card.pk, "card_number": card.card_number, "count": card.print_count})


@transaction.atomic
def resolve(actor, makerspace, payload):
    """Identify a member from a scanned card. Records the lookup even when it is refused."""
    _require(actor, rbac.Action.SCAN_MEMBER_CARDS, makerspace.pk)
    qr = QrCode.objects.filter(
        payload=payload, makerspace=makerspace, target_type=QrCode.TargetType.MEMBER_CARD
    ).first()
    if qr is None:
        # Uniform refusal: a payload from another tenant, a box QR, or nothing at all
        # all look the same to the scanner.
        raise Http404
    QrScanEvent.objects.create(
        makerspace=makerspace, qr_code=qr, actor=actor, context=QrScanEvent.Context.MEMBER_LOOKUP
    )
    card = MemberCard.objects.select_related("membership__user").filter(pk=qr.target_id, makerspace=makerspace).first()
    outcome = "ok"
    if qr.status != QrCode.Status.ACTIVE:
        outcome = "revoked"
    elif card is None or not card.is_active or card.membership.status != "active":
        outcome = "inactive"
    audit.record(actor, "member_card.scanned", makerspace=makerspace, target=card or qr, meta={"outcome": outcome, "qr_id": qr.pk})
    if outcome != "ok":
        return {"outcome": outcome}
    return {
        "outcome": "ok",
        "card_id": card.pk,
        "card_number": card.card_number,
        "printed_name": card.printed_name,
        "membership_id": card.membership_id,
        "membership_status": card.membership.status,
        "photo_url": member_card_storage.photo_url(card),
    }
