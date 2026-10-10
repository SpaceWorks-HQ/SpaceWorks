"""Tenure and concurrent pending limits, with immutable voucher accountability."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.membership_admission import OPEN_STATES, advance, transition
from apps.makerspaces.membership_admission_settings import AdmissionError, ensure_join_allowed, vouching_on
from apps.makerspaces.models import MakerspaceMembership, MembershipRequest, MembershipVouch


def valid_vouches(row, policy, *, now=None):
    now = now or timezone.now()
    eligible = MakerspaceMembership.objects.filter(
        makerspace=row.makerspace, status="active", user__is_active=True, user__access_status="active",
        activated_at__lte=now - timedelta(days=policy.voucher_min_tenure_days),
    ).values_list("user_id", flat=True)
    # For legacy rows with no activated_at, creation is the historical tenure start.
    legacy = MakerspaceMembership.objects.filter(
        makerspace=row.makerspace, status="active", user__is_active=True, user__access_status="active",
        activated_at__isnull=True, created_at__lte=now - timedelta(days=policy.voucher_min_tenure_days),
    ).values_list("user_id", flat=True)
    return row.vouches.filter(expires_at__gt=now, voucher_id__in=eligible.union(legacy))


def require_vouches(row, policy):
    if valid_vouches(row, policy).count() < policy.vouches_required:
        raise AdmissionError("membership_vouches_required", "This applicant still needs eligible vouches.")


def vouch_for_request(actor, row):
    with transaction.atomic():
        makerspace = require_module_locked(row.makerspace_id, "membership")
        policy = ensure_join_allowed(makerspace)
        row = MembershipRequest.objects.select_for_update().get(pk=row.pk, makerspace=makerspace)
        if not vouching_on(makerspace, policy):
            raise AdmissionError("membership_vouching_disabled", "Vouching is disabled for this makerspace.")
        if row.state not in ("awaiting_vouches", "requested", "awaiting_payment") or not row.user_id or row.user_id == actor.pk:
            raise AdmissionError("membership_vouch_unavailable", "This application cannot receive a vouch.")
        now = timezone.now()
        if row.expires_at and row.expires_at <= now:
            raise AdmissionError("membership_request_expired", "This membership application has expired.")
        membership = rbac.scope_by_makerspace(actor, MakerspaceMembership.objects.select_for_update()).filter(
            makerspace=makerspace, user=actor, status="active", user__is_active=True, user__access_status="active",
        ).first()
        if membership is None:
            raise PermissionDenied()
        since = membership.activated_at or membership.created_at
        if since > now - timedelta(days=policy.voucher_min_tenure_days):
            raise AdmissionError("membership_voucher_tenure", "You have not reached the minimum voucher tenure.")
        pending = MembershipVouch.objects.filter(
            makerspace=makerspace, voucher=actor, expires_at__gt=now,
            request__state__in=OPEN_STATES, request__expires_at__gt=now,
        ).count()
        if pending >= policy.voucher_pending_limit:
            raise AdmissionError("membership_voucher_limit", "You have reached the pending-applicant vouch limit.")
        if row.vouches.filter(voucher=actor).exists():
            raise AdmissionError("membership_vouch_exists", "You have already vouched for this application.")
        vouch = MembershipVouch.objects.create(
            makerspace=makerspace, request=row, voucher=actor,
            expires_at=now + timedelta(days=policy.vouch_expiry_days),
        )
        audit.record(actor, "membership.vouched", makerspace=makerspace, target=row,
                     meta={"vouch_id": vouch.pk, "voucher_id": actor.pk})
        if valid_vouches(row, policy, now=now).count() >= policy.vouches_required:
            if row.state == "awaiting_payment":
                advance(actor, row, policy)
                return row
            transition(actor, row, "requested", event="membership.vouches_satisfied")
            if policy.vouch_replaces_approval and not row.approved_at:
                row.approved_at = now
                # This is the approving person, not the applicant or a device.
                row.approved_by = actor
                row.save(update_fields=["approved_at", "approved_by"])
                return advance(actor, row, policy)
        return row


def flag_vouchers(actor, membership):
    """Accountability is evidence only; it never restricts a voucher's account."""
    ids = list(MembershipVouch.objects.filter(
        makerspace=membership.makerspace, request__user=membership.user, request__state="active",
    ).values_list("voucher_id", flat=True).distinct())
    if ids:
        audit.record(actor, "membership.vouchers_flagged", makerspace=membership.makerspace,
                     target=membership, meta={"voucher_ids": ids, "cause": "membership_revoked"})
