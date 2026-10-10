"""Database and catalog protections for manual refund receipts."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connections, transaction
from django.utils import timezone

from apps.backup.raw_projection import raw_records
from apps.data_export.archive import project_row
from apps.data_export.datasets import DATASETS
from apps.data_export.models import EXPORTED_MODEL_FIELDS
from apps.data_export.types import Fidelity
from apps.payments.exceptions_refunds import RefundNotAllowed
from apps.payments.models import Refund
from apps.payments.services_refunds_offline import record_offline_refund
from apps.tenant_migration.audit_references_meta_payments import PAYMENT_AUDIT_EDGES
from apps.tenant_migration.tenant_dump_catalog import FIELD_POLICIES, validate_catalog
from apps.tenant_migration.tenant_dump_types import AuthorityDisposition
from apps.tenant_migration.tenant_dump_raw import sanitize_record
from tests.payments.test_offline_refunds import cash_deposit, payload

pytestmark = pytest.mark.django_db


def test_manual_refunds_are_append_only_in_orm_and_database():
    _, staff, payment = cash_deposit("cash-immutable")
    refund = record_offline_refund(payment, actor=staff, **payload())
    refund.reference = "rewrite"
    with pytest.raises(ValidationError, match="append-only"):
        refund.save()
    with pytest.raises(ValidationError, match="append-only"):
        refund.delete()
    for operation in (
        lambda: Refund.objects.filter(pk=refund.pk).update(reference="rewrite"),
        lambda: Refund.objects.filter(pk=refund.pk).update(status="failed"),
        lambda: Refund.objects.filter(pk=refund.pk).delete(),
    ):
        with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
            operation()
    refund.refresh_from_db()
    assert refund.reference == "" and refund.status == "succeeded"


def test_raw_insert_cannot_skip_receipt_or_over_refund_validation():
    _, staff, payment = cash_deposit("cash-db-balance")
    record_offline_refund(payment, actor=staff, **payload("8.00"))
    refund = Refund(
        payment=payment, created_by=staff, amount=Decimal("3.00"), currency="usd",
        provider="manual", status="succeeded", method="cash", refunded_at=timezone.now(),
        settled_at=timezone.now(),
    )
    with pytest.raises(DatabaseError, match="exceed"), transaction.atomic():
        Refund.objects.bulk_create([refund])
    refund.amount = Decimal("1.00")
    refund.refunded_at = None
    with pytest.raises(DatabaseError), transaction.atomic():
        Refund.objects.bulk_create([refund])
    assert Refund.objects.filter(payment=payment).count() == 1


def test_purge_guard_is_the_only_database_delete_exception():
    _, staff, payment = cash_deposit("cash-purge")
    refund = record_offline_refund(payment, actor=staff, **payload())
    with transaction.atomic():
        with connections["default"].cursor() as cursor:
            cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
        Refund.objects.filter(pk=refund.pk).delete()
    assert not Refund.objects.filter(pk=refund.pk).exists()


def test_pending_online_attempts_hold_the_same_manual_refundable_balance():
    _, staff, payment = cash_deposit("cash-pending-balance")
    Refund.objects.create(payment=payment, amount=Decimal("8.00"), currency="usd",
                          provider="stripe", created_by=staff)
    with pytest.raises(RefundNotAllowed) as exc:
        record_offline_refund(payment, actor=staff, **payload("3.00"))
    assert exc.value.detail["code"] == "refund_exceeds_balance"
    record_offline_refund(payment, actor=staff, **payload("2.00"))
    assert Refund.counted_total(payment) == Decimal("10.00")


@pytest.mark.django_db(transaction=True)
def test_concurrent_releases_cannot_refund_the_same_deposit_twice():
    _, staff, payment = cash_deposit("cash-concurrent")
    barrier = Barrier(2)

    def release():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            record_offline_refund(payment, actor=staff, **payload("7.00"))
            return "recorded"
        except RefundNotAllowed as exc:
            return exc.detail["code"]
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: release(), range(2)))
    assert sorted(results) == ["recorded", "refund_exceeds_balance"]
    assert Refund.counted_total(payment) == Decimal("7.00")


def test_manual_receipt_fields_and_audit_ids_are_classified_for_export_and_tenant_dump():
    validate_catalog()
    for name in ("method", "reference", "refunded_at"):
        assert name in EXPORTED_MODEL_FIELDS["payments.Refund"]
        assert FIELD_POLICIES[("payments.Refund", name)].dispositions == (AuthorityDisposition.PRESERVE,)
    assert PAYMENT_AUDIT_EDGES[("payment.refund_recorded", "refund_id")].target_model_label == "payments.Refund"
    assert PAYMENT_AUDIT_EDGES[("payment.refund_recorded", "payment_id")].target_model_label == "payments.Payment"


def test_manual_receipt_survives_csv_and_portable_tenant_projection():
    _, staff, payment = cash_deposit("cash-export")
    refund = record_offline_refund(payment, actor=staff, **payload(reference="slip-9"))
    dataset = DATASETS[(Fidelity.PORTABLE, "payments/refunds.csv")]
    exported = project_row(dataset, refund, set())
    assert exported["method"] == "cash" and exported["reference"] == "slip-9"
    assert exported["refunded_at"] == refund.refunded_at.isoformat()
    source = raw_records(Refund.objects.filter(pk=refund.pk), Refund)[0]
    projected = sanitize_record(Refund, source).values
    for field in ("amount", "currency", "provider", "method", "reference", "refunded_at", "status"):
        assert projected[field] == source[field]
    assert projected["external_refund_id"] is None
