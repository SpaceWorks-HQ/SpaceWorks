from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit import services as audit
from apps.accounts.claim_sessions import (
    claim_context,
    token_payload_for_context,
    validated_claim_session,
)
from apps.makerspaces.models import MakerspaceMembership, presence_presets
from apps.presence.geofence import evaluate_geofence, geofence_metadata
from apps.presence.guard import MemberPresenceRequired
from apps.presence.models import PresenceSession


def _active_sessions(user, makerspace, now, *, claim_id=None):
    rows = PresenceSession.objects.select_for_update().filter(
        member=user,
        makerspace=makerspace,
        ended_at__isnull=True,
        expires_at__gt=now,
    )
    if claim_id is not None:
        rows = rows.filter(created_via_claim_session_id=claim_id)
    return rows.order_by("-started_at", "-id")


def start_session(user, makerspace, duration_minutes, *, latitude=None, longitude=None, accuracy=None):
    if duration_minutes not in presence_presets(makerspace):
        raise ValidationError({"duration_minutes": "Choose an allowed session length."})
    # ADVISORY by design (owner decision): browser-supplied coordinates are spoofable, so the geofence
    # is recorded for staff visibility but NEVER blocks a session. Do not convert this into a hard gate.
    geofence_result = evaluate_geofence(makerspace, latitude=latitude, longitude=longitude, accuracy=accuracy)
    context = claim_context(user)
    with transaction.atomic():
        claim = None
        if context is not None:
            claim = validated_claim_session(
                token_payload_for_context(context, user.pk), for_update=True
            )
            _validate_claim_scope(claim, user, makerspace)
        membership = MakerspaceMembership.objects.select_for_update().filter(
            makerspace=makerspace, user=user, status="active"
        ).first()
        if membership is None:
            raise MemberPresenceRequired()
        now = timezone.now()
        requested_duration = timedelta(minutes=duration_minutes)
        requested_expiry = now + requested_duration
        if claim is not None:
            requested_expiry = min(requested_expiry, claim.absolute_expires_at)
        active = list(
            _active_sessions(
                user,
                makerspace,
                now,
                claim_id=claim.pk if claim is not None else None,
            )
        )
        # Ordinary reuse is keyed on the session's DURATION, which is the shipped rule:
        # asking for the same length a moment later must return the same session, and
        # comparing against `now + duration` makes that impossible because the requested
        # expiry always moves forward. A claim-created start additionally requires the
        # existing session to sit inside the claim deadline, so the authorization a claim
        # produces can never outlive the claim itself.
        reusable = bool(
            active
            and active[0].expires_at - active[0].started_at == requested_duration
            and (claim is None or active[0].expires_at <= claim.absolute_expires_at)
        )
        if reusable:
            return active[0]
        for session in active:
            session.ended_at = now
            session.ended_by = user
            session.end_reason = PresenceSession.EndReason.SUPERSEDED
            session.save(update_fields=["ended_at", "ended_by", "end_reason"])
            audit.record(user, "presence.superseded", makerspace=makerspace, target=session)
        session = PresenceSession.objects.create(
            member=user,
            makerspace=makerspace,
            membership=membership,
            started_at=now,
            expires_at=requested_expiry,
            created_via_claim_session=claim,
        )
        audit.record(user, "presence.started", makerspace=makerspace, target=session, meta=geofence_metadata(geofence_result))
        return session


def current_session(user, makerspace):
    rows = PresenceSession.objects.filter(
        member=user, makerspace=makerspace, ended_at__isnull=True,
        expires_at__gt=timezone.now(),
    )
    context = claim_context(user)
    if context is not None:
        rows = rows.filter(created_via_claim_session__session_id=context.session_id)
    return rows.order_by("-started_at", "-id").first()


def end_session(user, makerspace):
    context = claim_context(user)
    with transaction.atomic():
        claim_id = None
        if context is not None:
            claim = validated_claim_session(
                token_payload_for_context(context, user.pk), for_update=True
            )
            _validate_claim_scope(claim, user, makerspace)
            claim_id = claim.pk
        session = _active_sessions(
            user, makerspace, timezone.now(), claim_id=claim_id
        ).first()
        if session is None:
            return None
        session.ended_at = timezone.now()
        session.ended_by = user
        session.end_reason = PresenceSession.EndReason.USER_ENDED
        session.save(update_fields=["ended_at", "ended_by", "end_reason"])
        audit.record(user, "presence.ended", makerspace=makerspace, target=session)
        return session


def end_sessions_for_membership(actor, membership, reason="membership_revoked"):
    now = timezone.now()
    for session in _active_sessions(membership.user, membership.makerspace, now):
        session.ended_at = now
        session.ended_by = actor
        session.end_reason = reason
        session.save(update_fields=["ended_at", "ended_by", "end_reason"])
        audit.record(actor, "presence.ended_membership_revoked", makerspace=membership.makerspace, target=session)


def end_sessions_for_claim(claim, *, ended_at, actor):
    """Lock claim then end exactly the active presence rows carrying its FK."""
    with transaction.atomic():
        from apps.accounts.models_claim import MemberClaimCode

        locked = (
            MemberClaimCode.objects.select_for_update(of=("self",))
            .select_related("membership")
            .get(pk=claim.pk)
        )
        if (
            locked.session_id != claim.session_id
            or locked.membership_id != claim.membership_id
        ):
            raise RuntimeError("Claim-session provenance is inconsistent.")
        sessions = list(
            PresenceSession.objects.select_for_update().filter(
                created_via_claim_session=locked,
                member_id=locked.membership.user_id,
                makerspace_id=locked.membership.makerspace_id,
                ended_at__isnull=True,
                expires_at__gt=ended_at,
            )
        )
        for session in sessions:
            session.ended_at = ended_at
            session.ended_by = actor
            session.end_reason = PresenceSession.EndReason.CLAIM_REVOKED
            session.save(update_fields=["ended_at", "ended_by", "end_reason"])
            audit.record(
                actor,
                "presence.ended_claim_revoked",
                makerspace=session.makerspace,
                target=session,
                meta={"claim_session_id": str(locked.session_id)},
            )


def expire_claim_presence(session_id):
    """End expired/revoked claim presence after a signed access token is rejected."""
    from apps.accounts.models_claim import MemberClaimCode

    claim = MemberClaimCode.objects.filter(session_id=session_id).first()
    now = timezone.now()
    if claim and (
        claim.revoked_at is not None
        or (claim.absolute_expires_at and claim.absolute_expires_at <= now)
    ):
        end_sessions_for_claim(claim, ended_at=now, actor=None)


def _validate_claim_scope(claim, user, makerspace):
    if (
        claim.membership.user_id != user.pk
        or claim.membership.makerspace_id != makerspace.pk
    ):
        raise PermissionDenied("Claim session does not belong to this member and makerspace.")
