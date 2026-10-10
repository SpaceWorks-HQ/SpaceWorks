"""Review regressions at the HTTP, ledger and notification boundaries."""
from decimal import Decimal
from datetime import timedelta
import uuid

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.makerspaces import membership_services
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole, MembershipRequest, MembershipVouch
from apps.payments.models import ManualSettlement, Payment
from apps.payments.reconciliation import mark_offline
from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
from apps.tenant_migration.models_source_gate import SourceMigrationGate
from tests.makerspaces.test_membership_admission_api import QUESTION, client
from tests.makerspaces.test_membership_admission_matrix import _application, _setup, _voucher
from tests.makerspaces.test_membership_j1 import member_role, space, user
from tests.return_helpers import settlement_details

pytestmark = pytest.mark.django_db(transaction=True)


def test_vouch_http_scopes_local_member_and_refuses_foreign_or_revoked_member():
    makerspace, _, applicant, _, _ = _setup("vouch")
    row = _application(makerspace, applicant)
    local, local_membership = _voucher(makerspace, "local-review-voucher")
    foreign, _ = _voucher(space("foreign-review-space"), "foreign-review-voucher")
    url = f"/api/v1/member/makerspaces/{makerspace.pk}/admission/{row.pk}/vouch"
    assert client(foreign).post(url).status_code == 404
    local_membership.status = "revoked"
    local_membership.save(update_fields=["status"])
    assert client(local).post(url).status_code == 404
    assert not MembershipVouch.objects.filter(request=row).exists()
    eligible, _ = _voucher(makerspace, "eligible-review-voucher")
    response = client(eligible).post(url)
    assert response.status_code == 200
    assert response.data == {"id": row.pk, "state": "requested"}
    assert MembershipVouch.objects.get(request=row).voucher_id == eligible.pk
    assert AuditLog.objects.filter(makerspace=makerspace, actor=eligible, action="membership.vouched").exists()


@pytest.mark.parametrize("settled", [False, True])
def test_revocation_cancels_only_unpaid_activate_then_charge_admission(settled):
    makerspace, actor, applicant, _, _ = _setup("open", True, "after_activation")
    row = _application(makerspace, applicant)
    payment = row.admission_payment
    if settled:
        mark_offline(payment, actor, settlement=settlement_details(reference="received-admission"))
    membership = MakerspaceMembership.objects.get(makerspace=makerspace, user=applicant)
    membership_services.revoke_membership(actor, membership, "Admission ended")
    membership.refresh_from_db()
    row.refresh_from_db()
    payment.refresh_from_db()
    assert membership.status == "revoked" and row.state == "active"
    assert payment.status == (Payment.Status.PAID_OFFLINE if settled else Payment.Status.CANCELED)
    assert payment.amount == Decimal("20.00")
    assert ManualSettlement.objects.filter(payment=payment).exists() == settled
    if not settled:
        assert AuditLog.objects.filter(makerspace=makerspace, actor=actor, action="payment.canceled",
                                       target_id=str(payment.pk)).exists()


def test_claimed_community_invitation_notifies_staff_of_received_application(monkeypatch):
    makerspace, actor, applicant, _, _ = _setup("invite_only", application_schema=QUESTION)
    row = membership_services.invite_membership(actor, makerspace, applicant.email, member_role(makerspace))
    received = []
    monkeypatch.setattr("apps.makerspaces.membership_notifications.notify_membership_request_pending",
                        lambda request: received.append((request.pk, request.user_id, request.admission_managed)))
    membership_services.claim_invitation(applicant, row.pk, {"why": "Learn safely"})
    row.refresh_from_db()
    assert received == [(row.pk, applicant.pk, True)]
    assert row.state == "requested"


def test_staff_invitation_discovery_identifies_core_claim_without_application_form():
    makerspace, actor, applicant, _, _ = _setup("approval", application_schema=QUESTION)
    role = MakerspaceRole.objects.get(makerspace=makerspace, slug="inventory_manager")
    row = membership_services.invite_membership(actor, makerspace, applicant.email, role)
    discovery = client(applicant).get("/api/v1/memberships/invitations")
    assert discovery.status_code == 200 and discovery.data["invitations"][0]["is_staff"] is True
    response = client(applicant).post(f"/api/v1/memberships/invitations/{row.pk}/claim", {}, format="json")
    assert response.status_code == 200 and response.data["outcome"] == "pending_approval"
    row.refresh_from_db()
    assert not row.admission_managed and row.application_answers is None


def test_roster_reviewer_cannot_read_admission_money_without_finance_authority():
    makerspace, actor, applicant, _, _ = _setup("approval", True, "before_activation")
    row = _application(makerspace, applicant)
    membership_services.approve_request(actor, row, member_role(makerspace))
    role = MakerspaceRole.objects.create(makerspace=makerspace, name="Review only", slug="review-only",
                                        granted_actions=["manage_members"])
    reviewer = user("review-only-actor")
    MakerspaceMembership.objects.create(makerspace=makerspace, user=reviewer, assigned_role=role)
    url = f"/api/v1/admin/membership-requests?makerspace_id={makerspace.pk}"
    review = client(reviewer).get(url)
    assert review.status_code == 200
    assert review.data["results"][0]["state"] == "awaiting_payment"
    assert review.data["results"][0]["admission_payment"] is None
    assert client(actor).get(url).data["results"][0]["admission_payment"]["amount"] == "20.00"
    own = client(applicant).get(f"/api/v1/member/makerspaces/{makerspace.pk}/admission")
    assert own.data["admission_payment"]["amount"] == "20.00"
    foreign = user("review-outside-actor")
    assert client(foreign).get(url).status_code in (403, 404)


@pytest.mark.parametrize("mode", ["open", "closed"])
def test_configured_staff_attachment_still_updates_an_existing_active_role(mode):
    from apps.admin_api.services_staff import attach_staff_membership

    makerspace, actor, applicant, _, _ = _setup(mode, True, "before_activation", application_schema=QUESTION)
    staff_role = MakerspaceRole.objects.get(makerspace=makerspace, slug="inventory_manager")
    existing = MakerspaceMembership.objects.create(makerspace=makerspace, user=applicant, assigned_role=staff_role)
    membership, created, _ = attach_staff_membership(actor=actor, makerspace=makerspace,
                                                     username=applicant.username, role=member_role(makerspace))
    membership.refresh_from_db()
    assert membership.pk == existing.pk and not created
    assert membership.assigned_role_id == member_role(makerspace).pk
    assert membership.status == "active"
    assert not MembershipRequest.objects.filter(makerspace=makerspace, user=applicant).exists()
    assert not Payment.objects.filter(makerspace=makerspace, member=applicant).exists()


def test_frozen_tenant_refuses_export_audit_and_direct_paid_activation(monkeypatch):
    from apps.makerspaces.membership_admission_payments import resume_after_payment

    makerspace, actor, applicant, _, _ = _setup("open", True, "before_activation")
    row = _application(makerspace, applicant)
    # Commit a real receipt while deferring activation until after the source freeze.
    with monkeypatch.context() as patch:
        patch.setattr("apps.payments.reconciliation.resume_admission_after_settlement", lambda payment: None)
        mark_offline(row.admission_payment, actor, settlement=settlement_details(reference="delayed-admission"))
    assert ManualSettlement.objects.filter(payment=row.admission_payment).exists()
    now = timezone.now()
    SourceMigrationGate.objects.create(makerspace=makerspace, state="quiesced", owner_id=uuid.uuid4(),
                                       heartbeat_at=now, lease_expires_at=now + timedelta(hours=1))
    count = AuditLog.objects.filter(makerspace=makerspace).count()
    response = client(applicant).get(f"/api/v1/member/makerspaces/{makerspace.pk}/admission/export")
    assert response.status_code == 423
    assert response.json()["code"] == "tenant_migration_quiesced"
    assert AuditLog.objects.filter(makerspace=makerspace).count() == count
    with pytest.raises(SourceMigrationGateClosed):
        resume_after_payment(row.admission_payment_id)
    row.refresh_from_db()
    assert row.state == "awaiting_payment"
    assert not MakerspaceMembership.objects.filter(makerspace=makerspace, user=applicant).exists()
    assert AuditLog.objects.filter(makerspace=makerspace).count() == count


def test_member_capability_mutation_keeps_scoped_voucher_accountability():
    from apps.makerspaces.membership_vouching import vouch_for_request

    makerspace, actor, applicant, _, _ = _setup("vouch")
    row = _application(makerspace, applicant)
    voucher, _ = _voucher(makerspace, "capability-review-voucher")
    vouch_for_request(voucher, row)
    membership = membership_services.approve_request(actor, row, member_role(makerspace))
    response = client(actor).patch(f"/api/v1/admin/memberships/{membership.pk}/capabilities",
                                  {"can_refer": True}, format="json")
    assert response.status_code == 200
    assert response.data["vouches"][0]["voucher_id"] == voucher.pk
