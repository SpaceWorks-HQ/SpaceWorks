"""Receipt numbering, immutable snapshots, refunds and authenticated custody."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, transaction
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.payments.documents import issue_receipt, issue_credit_note
from apps.payments.models import MakerspaceBillingSettings, Payment, PaymentDocument, Refund
from apps.payments.reconciliation import amend_settlement, mark_offline
from apps.payments.services_refunds import settle_refund
from apps.payments.services_refunds_offline import record_offline_refund, amend_offline_refund
from apps.payments.services_webhooks import apply_webhook_event
from apps.tenant_migration.money_digest import money_fingerprint
from tests.payments.test_refunds import paid_deposit
from tests.rbac_f6_helpers import custom_actor
from tests.return_helpers import authenticated_client, make_space, make_member, settlement_details

pytestmark = pytest.mark.django_db


def settled(slug="documents"):
    space = make_space(slug)
    staff = make_member(f"{slug}-staff", space)
    payment = paid_deposit(space, staff, status=Payment.Status.PENDING)
    mark_offline(payment, staff, settlement_details(reference="cash-1"))
    payment.refresh_from_db()
    return space, staff, payment


def test_issue_is_transactional_idempotent_and_snapshots_are_not_live():
    space, staff, payment = settled()
    doc = PaymentDocument.objects.get(payment=payment)
    assert doc.sequence == 1 and doc.number == "000001" and doc.kind == "receipt"
    assert doc.tax_breakdown is None and doc.amount == payment.amount
    assert doc.payer_label == payment.member.username
    assert issue_receipt(payment, actor=staff).pk == doc.pk
    policy = MakerspaceBillingSettings.objects.get(makerspace=space)
    policy.number_prefix = "SW-"
    policy.legal_name = "New legal name"
    policy.save()
    doc.refresh_from_db()
    assert doc.issuer["name"] == space.name and doc.number == "000001"
    next_payment = paid_deposit(space, staff, status="pending", intent="pi_next")
    mark_offline(next_payment, staff, settlement_details())
    assert PaymentDocument.objects.get(payment=next_payment).number == "SW-000002"
    assert AuditLog.objects.filter(action="payment.document_issued").count() == 2


def test_rollback_does_not_consume_a_document_number():
    space, staff, payment = settled("rollback-docs")
    next_payment = paid_deposit(space, staff, status="pending", intent="pi_rollback")
    with pytest.raises(RuntimeError), transaction.atomic():
        mark_offline(next_payment, staff, settlement_details())
        raise RuntimeError("roll back the settlement")
    next_payment.refresh_from_db()
    assert next_payment.status == "pending"
    assert not PaymentDocument.objects.filter(payment=next_payment).exists()
    mark_offline(next_payment, staff, settlement_details())
    assert list(PaymentDocument.objects.filter(makerspace=space).values_list("sequence", flat=True)) == [1, 2]


@pytest.mark.django_db(transaction=True)
def test_gapless_numbers_under_concurrent_settlements():
    space = make_space("concurrent-docs")
    staff = make_member("concurrent-docs-staff", space)
    payments = [paid_deposit(space, staff, status="pending", intent=f"pi_concurrent_{i}") for i in range(4)]
    barrier = Barrier(4)
    def run(payment):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            mark_offline(payment, staff, settlement_details())
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run, payments))
    assert list(PaymentDocument.objects.filter(makerspace=space).values_list("sequence", flat=True)) == [1, 2, 3, 4]
    assert MakerspaceBillingSettings.objects.get(makerspace=space).next_document_number == 5


def test_documents_refuse_model_and_database_mutation():
    _, _, payment = settled("immutable-docs")
    doc = PaymentDocument.objects.get(payment=payment)
    doc.number = "changed"
    with pytest.raises(ValidationError):
        doc.save()
    with pytest.raises(ValidationError):
        doc.delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        PaymentDocument.objects.filter(pk=doc.pk).update(number="changed")
    with pytest.raises(DatabaseError), transaction.atomic():
        PaymentDocument.objects.filter(pk=doc.pk).delete()


def test_manual_refund_and_corrections_append_offsetting_documents():
    _, staff, payment = settled("credit-docs")
    refund = record_offline_refund(payment, amount="4.00", reason="Return",
                                   receipt={"method": "cash", "reference": "refund-1", "refunded_at": timezone.now()}, actor=staff)
    credit = PaymentDocument.objects.get(refund=refund)
    assert credit.kind == "credit_note" and credit.amount == Decimal("4.00")
    assert issue_credit_note(refund, actor=staff).pk == credit.pk
    replacement = amend_offline_refund(payment, refund_id=refund.pk,
        receipt={"method": "upi", "reference": "refund-corrected", "refunded_at": timezone.now()}, actor=staff)
    assert PaymentDocument.objects.get(reverses=credit).kind == "receipt"
    assert PaymentDocument.objects.get(refund=replacement).kind == "credit_note"
    receipt = PaymentDocument.objects.get(payment=payment, kind="receipt", reverses__isnull=True)
    amend_settlement(actor=staff, makerspace_id=payment.makerspace_id, payment_id=payment.pk,
                     settlement=settlement_details(method="upi"))
    assert PaymentDocument.objects.get(reverses=receipt).kind == "credit_note"
    amounts = PaymentDocument.objects.filter(payment=payment)
    net = sum(row.amount if row.kind == "receipt" else -row.amount for row in amounts)
    assert net == Decimal("6.00")


def test_online_refund_succeeded_once_and_failed_attempt_gets_no_credit():
    space = make_space("online-credit")
    staff = make_member("online-credit-staff", space)
    payment = paid_deposit(space, staff)
    receipt = issue_receipt(payment)
    assert receipt.settlement_method == "stripe" and receipt.money_at == payment.updated_at
    refund = Refund.objects.create(payment=payment, amount="3.00", currency="usd", provider="stripe", created_by=staff)
    settle_refund(refund, external_refund_id="re_document", status="succeeded", actor=staff)
    settle_refund(refund, external_refund_id="re_document", status="succeeded", actor=staff)
    assert PaymentDocument.objects.filter(refund=refund).count() == 1
    failed = Refund.objects.create(payment=payment, amount="2.00", currency="usd", provider="stripe", created_by=staff)
    settle_refund(failed, external_refund_id="re_failed_document", status="failed", actor=staff)
    assert not PaymentDocument.objects.filter(refund=failed).exists()


def test_provider_settlement_and_replayed_event_issue_one_receipt():
    space = make_space("webhook-docs")
    staff = make_member("webhook-docs-staff", space)
    payment = paid_deposit(space, staff, status="pending", intent="pi_document_settlement")
    event = {"id": "evt_document", "type": "payment_intent.succeeded",
             "data": {"object": {"id": "pi_document_settlement"}}}
    apply_webhook_event(space, event)
    apply_webhook_event(space, event)
    assert PaymentDocument.objects.filter(payment=payment).count() == 1
    doc = PaymentDocument.objects.get(payment=payment)
    assert doc.kind == "receipt" and doc.issued_by is None


def test_document_grants_require_finance_or_payment_owner_and_expire():
    space, staff, payment = settled("scoped-docs")
    doc = PaymentDocument.objects.get(payment=payment)
    owner = authenticated_client(payment.member)
    path = reverse("member-payment-document-url", args=[space.pk, doc.pk])
    response = owner.get(path)
    assert response.status_code == 200 and response.data["expires_in"] == 300
    grant = response.data["url"]
    assert owner.get(grant).status_code == 200
    other = make_member("scoped-docs-other", space)
    assert authenticated_client(other).get(grant).status_code == 403
    assert authenticated_client(other).get(path).status_code == 404
    finance = custom_actor(space, ["view_finance"])
    staff_path = reverse("staff-payment-document-url", args=[space.pk, doc.pk])
    assert authenticated_client(finance).get(staff_path).status_code == 200
    cashier = custom_actor(space, ["record_payment"], name="docs-cashier")
    assert authenticated_client(cashier).get(staff_path).status_code == 404
    other_space = make_space("docs-foreign")
    assert authenticated_client(staff).get(reverse("staff-payment-document-url", args=[other_space.pk, doc.pk])).status_code == 404
    import time
    with patch("django.core.signing.time.time", return_value=time.time() + 306):
        assert owner.get(grant).status_code == 400


def test_mail_is_payer_only_and_failure_cannot_undo_settlement(monkeypatch, django_capture_on_commit_callbacks):
    calls = []
    def broken_mail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("SMTP unavailable")
    monkeypatch.setattr("apps.integrations.dispatch.dispatch_email", broken_mail)
    with django_capture_on_commit_callbacks(execute=True):
        _, _, payment = settled("mail-docs")
    assert calls[0]["to_email"] == payment.member.email
    assert calls[0]["persist_body"] is False
    payment.refresh_from_db()
    assert payment.status == "paid_offline" and PaymentDocument.objects.filter(payment=payment).exists()


def test_document_append_changes_money_fingerprint():
    space = make_space("document-digest")
    staff = make_member("document-digest-staff", space)
    payment = paid_deposit(space, staff)
    before = money_fingerprint(space.pk)
    issue_receipt(payment, actor=staff)
    assert money_fingerprint(space.pk) != before


def test_disable_issuance_preserves_existing_document_readability():
    space, staff, payment = settled("off-documents")
    space.enabled_features = [key for key in space.enabled_features if key != "billing.documents"]
    space.enabled_modules = []
    space.save(update_fields=["enabled_features", "enabled_modules"])
    new = paid_deposit(space, staff, status="pending", intent="pi_documents_off")
    mark_offline(new, staff, settlement_details())
    assert not PaymentDocument.objects.filter(payment=new).exists()
    response = authenticated_client(payment.member).get(reverse("member-payment-documents", args=[space.pk]))
    assert response.status_code == 200 and response.data["count"] == 1


def test_disabled_issuance_still_documents_refund_of_a_documented_charge():
    space, staff, payment = settled("refund-documents-off")
    space.enabled_features = [key for key in space.enabled_features if key != "billing.documents"]
    space.save(update_fields=["enabled_features"])
    refund = record_offline_refund(payment, amount="2.00", reason="Returned", actor=staff,
                                  receipt={"method": "cash", "reference": "", "refunded_at": timezone.now()})
    assert PaymentDocument.objects.get(refund=refund).kind == "credit_note"


def test_long_escaped_snapshot_renders_a_pdf_without_live_data():
    from apps.payments.document_pdf import render_document_pdf
    _, _, payment = settled("pdf-documents")
    doc = PaymentDocument.objects.get(payment=payment)
    # In-memory render fixture: the stored financial row remains immutable.
    doc.issuer = {"name": "Maker <&> Space", "address": "Long address " * 60,
                  "tax_id": "", "footer": "Footer text " * 80}
    result = render_document_pdf(doc)
    assert result.startswith(b"%PDF-") and len(result) > 1000


def test_revoked_payer_and_removed_finance_action_cannot_use_existing_grant():
    from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
    space, _, payment = settled("revoked-document-grants")
    doc = PaymentDocument.objects.get(payment=payment)
    member = MakerspaceMembership.objects.create(makerspace=space, user=payment.member, role="custom",
                                                 assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"))
    client = authenticated_client(payment.member)
    grant = client.get(reverse("member-payment-document-url", args=[space.pk, doc.pk])).data["url"]
    member.status = "revoked"
    member.save(update_fields=["status"])
    assert client.get(grant).status_code == 403
    staff = custom_actor(space, ["view_finance"])
    staff_client = authenticated_client(staff)
    staff_grant = staff_client.get(reverse("staff-payment-document-url", args=[space.pk, doc.pk])).data["url"]
    role = MakerspaceMembership.objects.get(user=staff, makerspace=space).assigned_role
    role.granted_actions = []
    role.save(update_fields=["granted_actions"])
    assert staff_client.get(staff_grant).status_code == 404


def test_billing_document_settings_validate_prefix_mapping_and_keep_counter_private():
    space, staff, _ = settled("document-policy")
    client = authenticated_client(staff)
    path = reverse("payment-billing-settings", args=[space.pk])
    assert client.patch(path, {"number_prefix": "bad/prefix"}, format="json").status_code == 400
    assert client.patch(path, {"account_codes": {"unknown_subject": "4000"}}, format="json").status_code == 400
    result = client.patch(path, {"number_prefix": "MS-", "account_codes": {"loan_deposit": "2101"},
                                 "next_document_number": 1000}, format="json")
    assert result.status_code == 200 and "next_document_number" not in result.data
    assert MakerspaceBillingSettings.objects.get(makerspace=space).next_document_number == 2


@pytest.mark.parametrize("field,value", [("access_status", "restricted"), ("access_status", "suspended"),
                                       ("is_active", False), ("must_change_password", True)])
def test_existing_staff_grant_rechecks_active_account(field, value):
    space, staff, payment = settled("staff-grant-active")
    doc = PaymentDocument.objects.get(payment=payment)
    client = authenticated_client(staff)
    grant = client.get(reverse("staff-payment-document-url", args=[space.pk, doc.pk])).data["url"]
    setattr(staff, field, value)
    staff.save(update_fields=[field])
    assert client.get(grant).status_code == 403


def test_existing_staff_grant_cannot_cross_a_tenant_browser_origin():
    from apps.makerspaces.models import Makerspace
    space, staff, payment = settled("staff-grant-origin")
    foreign = make_space("staff-grant-foreign-origin")
    foreign.frontend_domain = "foreign-documents.example.test"
    foreign.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    foreign.save(update_fields=["frontend_domain", "frontend_domain_status"])
    doc = PaymentDocument.objects.get(payment=payment)
    client = authenticated_client(staff)
    grant = client.get(reverse("staff-payment-document-url", args=[space.pk, doc.pk])).data["url"]
    assert client.get(grant, HTTP_ORIGIN=f"https://{foreign.frontend_domain}").status_code == 403


@pytest.mark.parametrize("changes", [
    {"issuer": []}, {"issuer": {"name": ""}},
    {"lines": [{"quantity": "1", "unit_amount": "10.00", "total": "10.00"}]},
    {"lines": [{"label": "Deposit", "quantity": "-1", "unit_amount": "-10.00", "total": "10.00"}]},
])
def test_malformed_snapshots_are_rejected_by_model_and_sql(changes):
    from copy import copy
    _, _, payment = settled("invalid-document-snapshot")
    original = PaymentDocument.objects.get(payment=payment)
    draft = copy(original)
    draft.pk = None
    draft.sequence = 2
    draft.number = "invalid-snapshot-2"
    for key, value in changes.items():
        setattr(draft, key, value)
    with pytest.raises(ValidationError):
        draft.clean()
    # bulk_create bypasses save/full_clean; the SQL guard must independently refuse.
    with pytest.raises(DatabaseError, match="invalid document issuer snapshot|document lines must reconcile"), transaction.atomic():
        PaymentDocument.objects.bulk_create([draft])


def test_document_cannot_reference_two_financial_sources():
    from copy import copy
    _, staff, payment = settled("mixed-document-source")
    refund = record_offline_refund(payment, amount="10.00", reason="Return", actor=staff,
                                  receipt={"method": "cash", "reference": "", "refunded_at": timezone.now()})
    draft = copy(PaymentDocument.objects.get(refund=refund))
    draft.pk = None
    draft.sequence = 3
    draft.number = "mixed-source-3"
    draft.reverses = PaymentDocument.objects.get(payment=payment, kind="receipt")
    with pytest.raises(ValidationError, match="only one financial source"):
        draft.clean()
    with pytest.raises(DatabaseError, match="only one financial source"), transaction.atomic():
        PaymentDocument.objects.bulk_create([draft])
