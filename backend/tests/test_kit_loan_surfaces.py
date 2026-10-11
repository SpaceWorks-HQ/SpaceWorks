import pytest

from apps.hardware_requests import self_checkout_workflow, direct_loan_workflow
from apps.hardware_requests.models import HardwareRequest, RequesterAccountability, ReturnEvent
from tests.kit_helpers import PRODUCT_KEY, issue_kit, kit_setup
from tests.return_helpers import authenticated_client, make_issue_evidence, make_return_evidence
from tests.test_public_self_checkout import eligible_member, make_qr

pytestmark = pytest.mark.django_db


def _enabled_setup():
    data = kit_setup()
    data.space.enabled_features = [*data.space.enabled_features, "inventory.self_checkout"]
    data.space.save(update_fields=["enabled_features"])
    data.product.public_self_checkout_enabled = True
    data.product.save(update_fields=["public_self_checkout_enabled"])
    data.borrower = eligible_member(data.space, "kit-member")
    return data


@pytest.mark.parametrize("surface", ["member", "direct"])
def test_all_loan_surfaces_record_checklists_and_missing_component_accountability(surface):
    data = _enabled_setup()
    evidence = make_issue_evidence(data.space, data.borrower if surface == "member" else data.actor)
    counts = [{"key": PRODUCT_KEY, "present": 12}]
    if surface == "member":
        qr = make_qr(data.space, data.product)
        loan = self_checkout_workflow.checkout_tool(data.space, data.borrower, qr.payload,
            evidence_id=evidence.pk, kit_checklist=counts)
    else:
        loan = direct_loan_workflow.issue_direct_loan(data.space, data.actor, borrower=data.borrower,
            evidence_id=evidence.pk, remark="Checked at issue", qr_payloads=[],
            items=[{"product_id": data.product.pk, "quantity": 1}], kit_checklist=counts)
    item = loan.request.items.get()
    assert item.issue_checklist[0]["present"] == 12
    returned_photo = make_return_evidence(data.space, data.borrower if surface == "member" else data.actor)
    if surface == "member":
        returned = self_checkout_workflow.return_tool(data.space, data.borrower, qr.payload,
            evidence_id=returned_photo.pk, remark="Inspected", kit_checklist=[{"key": PRODUCT_KEY, "present": 11}])
    else:
        returned = direct_loan_workflow.return_direct_loan(loan, data.actor, returned_photo.pk,
            "Inspected", [{"item_id": item.pk, "returned": 1, "damaged": 0, "missing": 0}],
            kit_checklist=[{"key": PRODUCT_KEY, "present": 11}])
    assert ReturnEvent.objects.get(request=loan.request).kit_checklist[0]["present"] == 11
    assert RequesterAccountability.objects.get(request=loan.request).quantity == 1
    returned.request.refresh_from_db()
    assert returned.request.status == HardwareRequest.Status.CLOSED_WITH_ISSUE


def test_staff_preview_scopes_every_reference_and_return_uses_issue_snapshot():
    data = kit_setup()
    issue_kit(data)
    foreign = kit_setup("foreign")
    client = authenticated_client(data.actor)
    url = f"/api/v1/admin/makerspace/{data.space.pk}/kit-checklist-preview"
    response = client.post(url, {"request_id": data.request.pk, "phase": "return",
        "resolutions": [{"item_id": data.item.pk, "returned": 1}]}, format="json")
    assert response.status_code == 200
    assert response.data["components"][0]["issue_present"] == 12
    assert client.post(url, {"request_id": foreign.request.pk}, format="json").status_code == 404
    assert client.post(url, {"container_id": foreign.box.pk}, format="json").status_code == 404
    assert client.post(url, {"items": [{"product_id": foreign.product.pk, "quantity": 1}]}, format="json").status_code == 404


def test_member_preview_refuses_another_borrowers_loan():
    data = _enabled_setup()
    qr = make_qr(data.space, data.product)
    self_checkout_workflow.checkout_tool(data.space, data.borrower, qr.payload,
        evidence_id=make_issue_evidence(data.space, data.borrower).pk,
        kit_checklist=[{"key": PRODUCT_KEY, "present": 12}])
    other_borrower = eligible_member(data.space, "other-kit-member")
    url = f"/api/v1/public/{data.space.slug}/tools/checklist"
    response = authenticated_client(other_borrower).post(url,
        {"payload": qr.payload, "phase": "return"}, format="json")
    assert response.status_code == 404
    own = authenticated_client(data.borrower).post(url,
        {"payload": qr.payload, "phase": "return"}, format="json")
    assert own.status_code == 200
    assert own.data["components"][0]["issue_present"] == 12


@pytest.mark.parametrize("bad", [
    [{"label": "Bits", "quantity": 0}], [{"label": "", "quantity": 1}],
    [{"key": "not-a-uuid", "label": "Bits", "quantity": 1}],
    [{"key": PRODUCT_KEY, "label": "Bits", "quantity": 1}] * 2,
])
def test_kit_definitions_are_bounded_and_validated_at_the_api_boundary(bad):
    data = kit_setup()
    response = authenticated_client(data.actor).patch(f"/api/v1/admin/inventory/{data.product.pk}",
                                                      {"kit_components": bad}, format="json")
    assert response.status_code == 400


def test_definition_edit_feature_off_and_foreign_product_refused():
    data = kit_setup()
    other = kit_setup("foreign")
    client = authenticated_client(data.actor)
    assert client.patch(f"/api/v1/admin/inventory/{other.product.pk}",
                        {"kit_components": []}, format="json").status_code == 404
    data.space.enabled_features = []
    data.space.save(update_fields=["enabled_features"])
    assert client.patch(f"/api/v1/admin/inventory/{data.product.pk}",
                        {"kit_components": []}, format="json").status_code == 400
