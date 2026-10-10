"""Vouches prove accountable eligibility without transferring access restrictions."""
from datetime import timedelta

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.audit.models import AuditLog
from apps.makerspaces import membership_services
from apps.makerspaces.membership_admission_payments import resume_after_payment
from apps.makerspaces.membership_admission_settings import AdmissionError
from apps.makerspaces.membership_vouching import valid_vouches, vouch_for_request
from apps.makerspaces.models import MakerspaceMembership, MembershipVouch
from apps.payments.models import ManualSettlement, Payment
from apps.payments.reconciliation import mark_offline
from tests.makerspaces.test_membership_admission_matrix import _application, _setup, _voucher
from tests.makerspaces.test_membership_j1 import member_role, space, user
from tests.return_helpers import settlement_details

pytestmark = pytest.mark.django_db(transaction=True)


def test_vouch_quorum_still_requires_staff_approval_by_default():
    makerspace, actor, applicant, _, policy = _setup("vouch", vouches_required=2)
    row = _application(makerspace, applicant)
    with pytest.raises(AdmissionError) as refused:
        membership_services.approve_request(actor, row, member_role(makerspace))
    assert refused.value.detail["code"] == "membership_vouches_required"
    first, _ = _voucher(makerspace, "first-voucher")
    second, _ = _voucher(makerspace, "second-voucher")
    vouch_for_request(first, row)
    row.refresh_from_db()
    assert row.state == "awaiting_vouches" and valid_vouches(row, policy).count() == 1
    with pytest.raises(AdmissionError):
        membership_services.approve_request(actor, row, member_role(makerspace))
    vouch_for_request(second, row)
    row.refresh_from_db()
    assert row.state == "requested" and row.approved_at is None
    assert not MakerspaceMembership.objects.filter(makerspace=makerspace, user=applicant).exists()
    membership_services.approve_request(actor, row, member_role(makerspace))
    row.refresh_from_db()
    assert row.state == "active"
    assert AuditLog.objects.filter(makerspace=makerspace, action="membership.vouched").count() == 2


@pytest.mark.parametrize("invalid", ["new", "revoked", "restricted", "suspended", "inactive", "foreign"])
def test_only_active_unrestricted_local_members_with_enough_tenure_can_vouch(invalid):
    makerspace, _, applicant, _, _ = _setup("vouch")
    row = _application(makerspace, applicant)
    voucher_space = space("foreign-voucher-space") if invalid == "foreign" else makerspace
    voucher, membership = _voucher(voucher_space, days=29 if invalid == "new" else 45)
    if invalid == "revoked":
        membership.status = "revoked"
        membership.save(update_fields=["status"])
    elif invalid in {"restricted", "suspended"}:
        voucher.access_status = invalid
        voucher.save(update_fields=["access_status"])
    elif invalid == "inactive":
        voucher.is_active = False
        voucher.save(update_fields=["is_active"])
    expected = AdmissionError if invalid == "new" else PermissionDenied
    with pytest.raises(expected):
        vouch_for_request(voucher, row)
    assert not MembershipVouch.objects.filter(request=row).exists()
    row.refresh_from_db()
    assert row.state == "awaiting_vouches"


def test_legacy_member_tenure_uses_creation_when_activation_timestamp_is_missing():
    makerspace, _, applicant, _, _ = _setup("vouch")
    row = _application(makerspace, applicant)
    voucher, membership = _voucher(makerspace)
    MakerspaceMembership.objects.filter(pk=membership.pk).update(
        activated_at=None, created_at=timezone.now() - timedelta(days=31),
    )
    vouch_for_request(voucher, row)
    assert MembershipVouch.objects.filter(request=row, voucher=voucher).exists()


def test_pending_applicant_limit_is_released_when_an_application_activates():
    makerspace, actor, applicant, _, _ = _setup("vouch", voucher_pending_limit=1)
    first = _application(makerspace, applicant)
    second = _application(makerspace, user("second-pending-applicant"))
    voucher, _ = _voucher(makerspace)
    vouch_for_request(voucher, first)
    with pytest.raises(AdmissionError) as refused:
        vouch_for_request(voucher, second)
    assert refused.value.detail["code"] == "membership_voucher_limit"
    assert MembershipVouch.objects.filter(voucher=voucher).count() == 1
    membership_services.approve_request(actor, first, member_role(makerspace))
    vouch_for_request(voucher, second)
    assert MembershipVouch.objects.filter(voucher=voucher).count() == 2


def test_duplicate_vouch_and_model_or_database_edits_are_refused():
    makerspace, _, applicant, _, _ = _setup("vouch")
    row = _application(makerspace, applicant)
    voucher, _ = _voucher(makerspace)
    vouch_for_request(voucher, row)
    with pytest.raises(AdmissionError) as refused:
        vouch_for_request(voucher, row)
    assert refused.value.detail["code"] == "membership_vouch_exists"
    vouch = MembershipVouch.objects.get(request=row)
    with pytest.raises(RuntimeError, match="immutable"):
        vouch.save()
    with pytest.raises(RuntimeError, match="immutable"):
        vouch.delete()
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            MembershipVouch.objects.filter(pk=vouch.pk).update(expires_at=timezone.now() + timedelta(days=90))
    vouch.refresh_from_db()
    assert MembershipVouch.objects.filter(request=row).count() == 1
    assert vouch.voucher_id == voucher.pk


def test_expired_vouch_no_longer_counts_or_occupies_pending_capacity(monkeypatch):
    makerspace, actor, applicant, _, policy = _setup("vouch", vouch_expiry_days=1, voucher_pending_limit=1)
    row = _application(makerspace, applicant)
    voucher, _ = _voucher(makerspace)
    vouch_for_request(voucher, row)
    immutable_expiry = MembershipVouch.objects.get(request=row).expires_at
    monkeypatch.setattr(timezone, "now", lambda: immutable_expiry + timedelta(seconds=1))
    assert valid_vouches(row, policy).count() == 0
    with pytest.raises(AdmissionError) as refused:
        membership_services.approve_request(actor, row, member_role(makerspace))
    assert refused.value.detail["code"] == "membership_vouches_required"
    other = _application(makerspace, user("after-vouch-expiry"))
    vouch_for_request(voucher, other)
    assert MembershipVouch.objects.filter(voucher=voucher).count() == 2
    assert MembershipVouch.objects.get(request=row).expires_at == immutable_expiry


@pytest.mark.parametrize("paid", [False, True])
def test_vouch_can_replace_approval_but_cannot_replace_payment(paid):
    makerspace, actor, applicant, _, _ = _setup(
        "vouch", paid, "before_activation", vouch_replaces_approval=True,
    )
    row = _application(makerspace, applicant)
    voucher, _ = _voucher(makerspace)
    vouch_for_request(voucher, row)
    row.refresh_from_db()
    assert row.approved_at is not None and row.approved_by_id == voucher.pk
    assert row.state == ("awaiting_payment" if paid else "active")
    if paid:
        assert not MakerspaceMembership.objects.filter(makerspace=makerspace, user=applicant).exists()
        mark_offline(row.admission_payment, actor, settlement=settlement_details())
        row.refresh_from_db()
        assert row.state == "active"


@pytest.mark.parametrize("loss", ["revoked", "restricted", "expired"])
def test_settlement_rechecks_vouchers_and_replacement_recovers_paid_admission(loss, monkeypatch):
    makerspace, actor, applicant, _, _ = _setup(
        "vouch", True, "before_activation", vouch_expiry_days=1,
    )
    row = _application(makerspace, applicant)
    voucher, membership = _voucher(makerspace, "original-voucher")
    vouch_for_request(voucher, row)
    membership_services.approve_request(actor, row, member_role(makerspace))
    row.refresh_from_db()
    original_approval = row.approved_at
    payment = row.admission_payment
    if loss == "revoked":
        membership_services.revoke_membership(actor, membership)
    elif loss == "restricted":
        voucher.access_status = "restricted"
        voucher.save(update_fields=["access_status"])
    else:
        expiry = MembershipVouch.objects.get(request=row).expires_at
        monkeypatch.setattr(timezone, "now", lambda: expiry + timedelta(seconds=1))
    mark_offline(payment, actor, settlement=settlement_details(reference="vouch-recheck"))
    row.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_OFFLINE
    assert ManualSettlement.objects.filter(payment=payment).exists()
    assert row.state == "awaiting_payment" and row.approved_at == original_approval
    assert not MakerspaceMembership.objects.filter(makerspace=makerspace, user=applicant).exists()
    with pytest.raises(AdmissionError):
        resume_after_payment(payment.pk)
    replacement, _ = _voucher(makerspace, "replacement-voucher")
    vouch_for_request(replacement, row)
    row.refresh_from_db()
    assert row.state == "active" and row.approved_at == original_approval
    assert Payment.objects.filter(subject_type="membership_request", subject_id=row.pk).count() == 1
    assert MembershipVouch.objects.filter(request=row).count() == 2


def test_revocation_flags_vouchers_without_restricting_them():
    makerspace, actor, applicant, _, _ = _setup("vouch")
    row = _application(makerspace, applicant)
    voucher, voucher_membership = _voucher(makerspace)
    vouch_for_request(voucher, row)
    membership = membership_services.approve_request(actor, row, member_role(makerspace))
    membership_services.revoke_membership(actor, membership, reason="Member accountability")
    voucher.refresh_from_db()
    voucher_membership.refresh_from_db()
    assert voucher.access_status == "active" and voucher_membership.status == "active"
    flag = AuditLog.objects.get(makerspace=makerspace, action="membership.vouchers_flagged")
    assert flag.meta["voucher_ids"] == [voucher.pk]
    assert flag.actor_id == actor.pk
    assert MembershipVouch.objects.filter(request=row, voucher=voucher).exists()
