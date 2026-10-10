from datetime import timedelta

import pytest
from django.utils import timezone

from apps.evidence.storage import EvidenceValidationResult
from apps.hardware_requests.models import PublicToolLoan
from apps.makerspaces.models_loan_policy import MakerspaceLoanPolicy
from tests import test_admin_direct_loans as direct
from tests import test_public_self_checkout as public

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def uploaded_evidence(monkeypatch, settings):
    settings.API_CLIENT_AUTH_REQUIRED = False
    monkeypatch.setattr("apps.evidence.storage.finalize_upload",
                        lambda evidence, max_bytes: EvidenceValidationResult(size=123, content_type="image/png"))


def test_direct_bundle_uses_shortest_product_period_and_borrow_limit_rolls_back_stock():
    space = direct.make_space("bundle-policy")
    staff = direct.make_admin(space)
    borrower = direct.eligible_member(space)
    space.enabled_features = sorted(set(space.enabled_features) | {"loans.limits"})
    space.save(update_fields=["enabled_features"])
    policy = MakerspaceLoanPolicy.objects.create(makerspace=space, default_loan_days=5, loan_max_items=1)
    first = direct.make_product(space, name="First", loan_days=2)
    second = direct.make_product(space, name="Second", loan_days=1)
    client = direct.authed(staff)
    payload = direct.direct_payload(makerspace=space, borrower=borrower,
                                    items=[{"product_id": first.pk, "quantity": 1},
                                           {"product_id": second.pk, "quantity": 1}])
    path = direct.direct_url(space)
    assert client.post(path, payload, format="json").status_code == 400
    first.refresh_from_db(); second.refresh_from_db()
    assert first.available_quantity == second.available_quantity == 3
    assert not PublicToolLoan.objects.filter(makerspace=space).exists()
    policy.loan_max_items = 2
    policy.save()
    before = timezone.now()
    assert client.post(path, payload, format="json").status_code == 201
    loan = PublicToolLoan.objects.get(makerspace=space)
    assert before + timedelta(days=1) <= loan.due_at <= timezone.now() + timedelta(days=1)
    assert loan.request.return_due_at == loan.due_at


def test_public_checkout_uses_policy_period_and_refuses_second_active_loan():
    space = public.make_space("self-policy")
    borrower = public.eligible_member(space, username="self-policy-member")
    space.enabled_features = sorted(set(space.enabled_features) | {"loans.limits", "inventory.self_checkout"})
    space.save(update_fields=["enabled_features"])
    MakerspaceLoanPolicy.objects.create(makerspace=space, default_loan_days=3, loan_max_active=1)
    first = public.make_product(space, public_self_checkout_enabled=True)
    qr = public.make_qr(space, first)
    client = public.member_client(borrower)
    before = timezone.now()
    assert client.post(public.checkout_url(space), public.checkout_payload(space, borrower, qr.payload), format="json").status_code == 201
    loan = PublicToolLoan.objects.get(makerspace=space)
    assert before + timedelta(days=3) <= loan.due_at <= timezone.now() + timedelta(days=3)
    second = public.make_product(space, name="Second", public_self_checkout_enabled=True)
    other_qr = public.make_qr(space, second)
    response = client.post(public.checkout_url(space), public.checkout_payload(space, borrower, other_qr.payload), format="json")
    assert response.status_code == 400
    second.refresh_from_db()
    assert second.available_quantity == 2 and second.issued_quantity == 0
    assert PublicToolLoan.objects.filter(makerspace=space).count() == 1
