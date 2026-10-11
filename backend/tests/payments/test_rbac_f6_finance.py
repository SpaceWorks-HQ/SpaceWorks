"""Read-only treasurers and cashiers have independent, tenant-scoped authority."""
import pytest
from django.utils import timezone

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace
from apps.payments.models import ManualSettlement, Refund
from tests.module_helpers import disable_module
from tests.payments.test_purged_machine_charge import machine_charge
from tests.rbac_f6_helpers import charge, community_member, custom_actor
from tests.return_helpers import authenticated_client, make_member, make_space, make_user, settlement_payload

pytestmark = pytest.mark.django_db


def finance_route(case, space):
    member = community_member(space)
    payment = charge(space, member, status="paid_offline" if case in {"amend", "refund"} else "pending")
    base = f"/api/v1/admin/makerspace/{space.pk}"
    if case in {"amend", "refund"}:
        ManualSettlement.objects.create(
            payment=payment, amount=payment.amount, currency=payment.currency,
            method="cash", received_at=timezone.now(), recorded_by=member.user,
        )
    routes = {
        "list": ("get", f"{base}/payments", None),
        "counter": ("get", f"{base}/payments?for_recording=true", None),
        "report": ("get", f"{base}/analytics/payment-reconciliation", None),
        "export": ("get", f"{base}/reports/payment-reconciliation/export?format=csv", None),
        "mark": ("post", f"{base}/payments/{payment.pk}/mark-offline", settlement_payload()),
        "bulk": ("post", f"{base}/payments/bulk/mark-offline", {"ids": [payment.pk], **settlement_payload()}),
        "amend": ("post", f"{base}/payments/{payment.pk}/amend-settlement", settlement_payload(reference="corrected")),
        "refund": ("post", f"{base}/payments/{payment.pk}/refund-offline", {
            "amount": "2.00", "reason": "Returned cash", "receipt": {
                "method": "cash", "reference": "refund-1", "refunded_at": timezone.now().isoformat(),
            },
        }),
    }
    return payment, routes[case]


@pytest.mark.parametrize("case", ["list", "counter", "report", "export", "mark", "bulk", "amend", "refund"])
@pytest.mark.parametrize("authority", ["narrow", "missing", "foreign", "inventory", "hidden-superadmin"])
def test_finance_endpoint_matrix(case, authority):
    space = make_space("f6-finance-matrix")
    payment, (method, path, body) = finance_route(case, space)
    action = rbac.Action.VIEW_FINANCE if case in {"list", "report", "export"} else rbac.Action.RECORD_PAYMENT
    if authority == "hidden-superadmin":
        Makerspace.objects.filter(pk=space.pk).update(superadmin_access_enabled=False)
        actor = make_user("f6-money-hidden", role="superadmin", access_status="active")
    elif authority == "inventory":
        actor = make_member("f6-money-inventory", space, membership_role="inventory_manager", role="requester")
    else:
        actor_space = make_space("f6-finance-other") if authority == "foreign" else space
        actor = custom_actor(actor_space, [] if authority == "missing" else [action])
    response = getattr(authenticated_client(actor), method)(path, body, format="json")
    if authority == "narrow":
        assert response.status_code == 200
        if method == "post":
            assert AuditLog.objects.filter(actor=actor, makerspace=space, target_id=str(payment.pk)).exists()
            if case in {"mark", "bulk"}:
                assert ManualSettlement.objects.filter(payment=payment, recorded_by=actor).exists()
            if case == "amend":
                assert ManualSettlement.objects.filter(payment=payment).count() == 2
            if case == "refund":
                assert Refund.objects.filter(payment=payment, created_by=actor, provider="manual").exists()
    else:
        assert response.status_code in (403, 404)
        assert not AuditLog.objects.filter(actor=actor, makerspace=space).exists()


def test_read_only_finance_cannot_record_correct_refund_or_waive():
    space = make_space("f6-read-only")
    actor = custom_actor(space, [rbac.Action.VIEW_FINANCE])
    client = authenticated_client(actor)
    payment = charge(space, community_member(space))
    base = f"/api/v1/admin/makerspace/{space.pk}/payments"
    for suffix, body in [
        ("mark-offline", settlement_payload()), ("waive", {}),
        ("amend-settlement", settlement_payload()),
        ("refund-offline", {"amount": "1.00", "receipt": {"method": "cash", "refunded_at": timezone.now().isoformat()}}),
    ]:
        assert client.post(f"{base}/{payment.pk}/{suffix}", body, format="json").status_code in (403, 404)
    payment.refresh_from_db()
    assert payment.status == "pending"
    assert not ManualSettlement.objects.filter(payment=payment).exists()
    assert not Refund.objects.filter(payment=payment).exists()


def test_cashier_has_counter_rows_but_no_ledger_reports_waives_or_provider_refunds():
    space = make_space("f6-cashier")
    actor = custom_actor(space, [rbac.Action.RECORD_PAYMENT])
    pending = charge(space, community_member(space, "pending"))
    charge(space, community_member(space, "online"), status="paid_online")
    charge(space, community_member(space, "waived"), status="waived")
    offline = charge(space, community_member(space, "offline"), status="paid_offline")
    client = authenticated_client(actor)
    base = f"/api/v1/admin/makerspace/{space.pk}"
    response = client.get(f"{base}/payments?for_recording=true")
    assert response.status_code == 200
    assert {row["id"] for row in response.data["results"]} == {pending.pk, offline.pk}
    assert client.get(f"{base}/payments").status_code == 404
    assert client.get(f"{base}/analytics/payment-reconciliation").status_code == 404
    assert client.post(f"{base}/payments/{pending.pk}/waive", {}, format="json").status_code == 403
    assert client.post(f"{base}/payments/{pending.pk}/refund", {"amount": "1.00"}, format="json").status_code == 403
    assert client.get(f"{base}/payments?for_recording=invalid").status_code == 400


def test_cash_work_and_finance_reads_survive_payments_module_off():
    space = make_space("f6-money-off")
    actor = custom_actor(space, [rbac.Action.VIEW_FINANCE, rbac.Action.RECORD_PAYMENT])
    payment = charge(space, community_member(space))
    disable_module(space, "payments")
    client = authenticated_client(actor)
    base = f"/api/v1/admin/makerspace/{space.pk}"
    assert client.get(f"{base}/payments").status_code == 200
    assert client.get(f"{base}/analytics/payment-reconciliation").status_code == 200
    assert client.post(f"{base}/payments/{payment.pk}/mark-offline", settlement_payload(), format="json").status_code == 200


def test_record_authority_crosses_subjects_without_conferring_machine_authority():
    space = make_space("f6-cash-subjects")
    actor = custom_actor(space, [rbac.Action.RECORD_PAYMENT])
    member = community_member(space)
    payment, _request = machine_charge(space, member.user)
    response = authenticated_client(actor).post(
        f"/api/v1/admin/makerspace/{space.pk}/payments/{payment.pk}/mark-offline",
        settlement_payload(), format="json",
    )
    assert response.status_code == 200
    assert not rbac.can(actor, rbac.Action.MANAGE_MACHINES, space.pk)
