"""Review regressions for kit composition, scoped reads and transactional edits."""

import pytest
from django.db import transaction
from types import SimpleNamespace

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.hardware_requests import kit_checklists as kits, workflow
from apps.hardware_requests.models import HardwareRequestItem, RequesterAccountability, ReturnEvent
from apps.inventory import availability
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.procurement.models import ToBuyItem
from tests.kit_helpers import BOX_KEY, PRODUCT_KEY, issue_kit, kit_setup, return_kit
from tests.return_helpers import authenticated_client, make_issue_evidence, make_return_evidence, make_product

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("same_product", [False, True])
def test_copied_component_keys_do_not_block_composed_kits_or_mix_accountability(same_product):
    data = kit_setup()
    product = data.product if same_product else make_product(data.space, name="Second kit",
                                                            kit_components=data.product.kit_components)
    extra = HardwareRequestItem.objects.create(request=data.request, product=product,
                                               requested_quantity=1, accepted_quantity=1)
    # Reserve only the new line: the first was already reserved by the fixture.
    with transaction.atomic():
        availability.reserve_for_request(SimpleNamespace(items=data.request.items.filter(pk=extra.pk)))
    data.request = workflow.assign_box(data.actor, data.request, data.box.code)
    preview = kits.issue_expectations(data.request, data.box)
    keys = [row["key"] for row in preview]
    assert len(keys) == len(set(keys)) == 2
    data.request = workflow.issue_request(data.actor, data.request,
        make_issue_evidence(data.space, data.actor).pk,
        kit_checklist=[{"key": key, "present": 12} for key in keys])
    data.item.refresh_from_db()
    extra.refresh_from_db()
    first_key = data.item.issue_checklist[0]["key"]
    second_key = extra.issue_checklist[0]["key"]
    workflow.return_items(data.actor, data.request, make_return_evidence(data.space, data.actor).pk,
        "Inspected both kits", data.box.code,
        [{"item_id": item.pk, "returned": 1, "damaged": 0, "missing": 0} for item in (data.item, extra)],
        kit_checklist=[{"key": first_key, "present": 12}, {"key": second_key, "present": 11}])
    missing = RequesterAccountability.objects.get(request=data.request)
    assert missing.request_item_id == extra.pk
    assert missing.quantity == 1


def test_box_checklist_is_requested_only_on_the_final_partial_return():
    data = kit_setup(quantity=2, box_kit=True)
    issue_kit(data)
    data.request = return_kit(data, [{"key": PRODUCT_KEY, "present": 12}], quantity=1)
    assert ReturnEvent.objects.get(request=data.request).kit_checklist[0]["key"] == PRODUCT_KEY
    data.request = return_kit(data, [{"key": PRODUCT_KEY, "present": 12},
                                   {"key": BOX_KEY, "present": 0}], quantity=1)
    assert RequesterAccountability.objects.get(request=data.request).request_item_id is None


def test_reorder_readers_can_view_suggestions_but_cannot_create_drafts():
    data = kit_setup()
    data.product.reorder_point = 10
    data.product.reorder_quantity = 3
    data.product.save(update_fields=["reorder_point", "reorder_quantity"])
    role = MakerspaceRole.objects.create(makerspace=data.space, name="Inventory reader", slug="inventory-reader",
                                        granted_actions=[rbac.Action.VIEW_INVENTORY])
    membership = MakerspaceMembership.objects.get(user=data.actor, makerspace=data.space)
    membership.assigned_role = role
    membership.save(update_fields=["assigned_role"])
    client = authenticated_client(data.actor)
    base = f"/api/v1/admin/makerspace/{data.space.pk}/inventory"
    assert client.get(f"{base}/reorder-suggestions").data["results"][0]["id"] == data.product.pk
    assert client.post(f"{base}/reorder-draft", {"product_id": data.product.pk}, format="json").status_code == 404
    assert not ToBuyItem.objects.exists()


def test_reorder_reuse_cannot_return_a_printing_draft():
    data = kit_setup()
    data.product.reorder_point = 10
    data.product.reorder_quantity = 3
    data.product.save(update_fields=["reorder_point", "reorder_quantity"])
    printing = ToBuyItem.objects.create(makerspace=data.space, kind=ToBuyItem.Kind.PRINTING,
        name="Printing supply", quantity=1, source_product=data.product, created_by=data.actor)
    response = authenticated_client(data.actor).post(
        f"/api/v1/admin/makerspace/{data.space.pk}/inventory/reorder-draft",
        {"product_id": data.product.pk}, format="json")
    assert response.status_code == 201
    assert response.data["id"] != printing.pk
    assert response.data["kind"] == ToBuyItem.Kind.HARDWARE


@pytest.mark.parametrize("surface", ["patch", "move"])
def test_container_edit_rejects_cycles_and_foreign_parents_without_an_audit(surface):
    data = kit_setup()
    foreign = kit_setup("foreign")
    client = authenticated_client(data.actor)
    path = f"/api/v1/admin/containers/{data.box.pk}" + ("/move" if surface == "move" else "")
    submit = client.post if surface == "move" else client.patch
    field = "parent_id" if surface == "move" else "parent"
    for parent in (data.box, foreign.box):
        response = submit(path, {field: parent.pk}, format="json")
        assert response.status_code in (400, 404)
    data.box.refresh_from_db()
    assert data.box.parent_id is None
    assert not AuditLog.objects.filter(makerspace=data.space, action="container.moved").exists()


@pytest.mark.parametrize("surface", ["patch", "move"])
def test_container_edit_rolls_back_if_audit_cannot_be_written(surface, monkeypatch):
    data = kit_setup()
    client = authenticated_client(data.actor)
    path = f"/api/v1/admin/containers/{data.box.pk}" + ("/move" if surface == "move" else "")
    submit = client.post if surface == "move" else client.patch
    def fail(*args, **kwargs):
        raise RuntimeError("Audit unavailable")
    monkeypatch.setattr("apps.operations.views_containers.audit.record", fail)
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        submit(path, {"kit_components": [{"key": BOX_KEY, "label": "Strap", "quantity": 1}]}, format="json")
    data.box.refresh_from_db()
    assert data.box.kit_components == []


def test_direct_checklist_preview_honors_feature_and_container_module_gates():
    data = kit_setup()
    client = authenticated_client(data.actor)
    path = f"/api/v1/admin/makerspace/{data.space.pk}/kit-checklist-preview"
    data.space.enabled_features = ["loans.kit_checklist"]
    data.space.save(update_fields=["enabled_features"])
    assert client.post(path, {"items": [{"product_id": data.product.pk, "quantity": 1}]},
                       format="json").status_code == 400
    data.space.enabled_features = ["inventory.self_checkout"]
    data.space.enabled_modules = [key for key in data.space.enabled_modules if key != "containers"]
    data.space.save(update_fields=["enabled_features", "enabled_modules"])
    assert client.post(path, {"container_id": data.box.pk}, format="json").status_code == 400


def test_product_master_data_edit_is_atomic_with_its_audit(monkeypatch):
    data = kit_setup()
    def fail(*args, **kwargs):
        raise RuntimeError("Audit unavailable")
    monkeypatch.setattr("apps.admin_api.views_inventory_products.audit.record", fail)
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        authenticated_client(data.actor).patch(f"/api/v1/admin/inventory/{data.product.pk}",
                                              {"supplier": "New supplier"}, format="json")
    data.product.refresh_from_db()
    assert data.product.supplier == ""


def test_stale_product_edit_cannot_write_kit_after_feature_disabled():
    from apps.admin_api.serializers_inventory_products import InventoryProductAdminUpdateSerializer
    from rest_framework.exceptions import ValidationError
    data = kit_setup()
    # Load the relation before changing the stored gates, reproducing a stale view lookup.
    assert "loans.kit_checklist" in data.product.makerspace.enabled_features
    data.space.enabled_features = []
    data.space.save(update_fields=["enabled_features"])
    serializer = InventoryProductAdminUpdateSerializer(data.product, data={"kit_components": []}, partial=True)
    serializer.is_valid(raise_exception=True)
    with pytest.raises(ValidationError):
        serializer.save()
    data.product.refresh_from_db()
    assert data.product.kit_components[0]["label"] == "Driver bits"


def test_direct_preview_and_issue_agree_for_copied_product_and_box_components():
    from apps.hardware_requests.direct_loan_workflow import issue_direct_loan
    from apps.hardware_requests.kit_preview import preview_targets
    from tests.test_public_self_checkout import eligible_member
    data = kit_setup()
    data.box.kit_components = data.product.kit_components
    data.box.save(update_fields=["kit_components"])
    borrower = eligible_member(data.space, "composed-kit-borrower")
    items = [{"product_id": data.product.pk, "quantity": 1}]
    preview = preview_targets(data.actor, data.space, items=items, container_id=data.box.pk)
    assert len({row["key"] for row in preview}) == 2
    loan = issue_direct_loan(data.space, data.actor, borrower=borrower,
        evidence_id=make_issue_evidence(data.space, data.actor).pk, remark="Counted",
        qr_payloads=[], items=items, container_id=data.box.pk,
        kit_checklist=[{"key": row["key"], "present": row["quantity"]} for row in preview])
    recorded = loan.request.items.get().issue_checklist + loan.request.box_issue_checklist
    assert {row["key"] for row in recorded} == {row["key"] for row in preview}


def test_box_kit_can_issue_its_asset_when_another_unit_is_available_outside():
    from apps.boxes.models import QrCode
    from apps.inventory.models import InventoryAsset, TrackingMode
    from tests.test_public_self_checkout import eligible_member
    data = kit_setup()
    product = make_product(data.space, name="Asset kit", box=data.box, tracking_mode=TrackingMode.INDIVIDUAL,
        public_self_checkout_enabled=True, kit_components=data.product.kit_components,
        total_quantity=2, available_quantity=2)
    inside = InventoryAsset.objects.create(makerspace=data.space, product=product, box=data.box,
                                            asset_tag="inside", public_self_checkout_enabled=True)
    outside = InventoryAsset.objects.create(makerspace=data.space, product=product,
                                             asset_tag="outside", public_self_checkout_enabled=True)
    qr = QrCode.objects.create(makerspace=data.space, target_type=QrCode.TargetType.BOX, target_id=data.box.pk)
    borrower = eligible_member(data.space, "box-kit-borrower")
    response = authenticated_client(borrower).post(f"/api/v1/public/{data.space.slug}/tools/checkout", {
        "payload": qr.payload, "evidence_id": make_issue_evidence(data.space, borrower).pk,
        "kit_checklist": [{"key": PRODUCT_KEY, "present": 12}],
    }, format="json")
    assert response.status_code == 201, response.data
    product.refresh_from_db()
    inside.refresh_from_db()
    outside.refresh_from_db()
    assert (product.available_quantity, product.issued_quantity) == (1, 1)
    assert inside.status == InventoryAsset.Status.ISSUED
    assert outside.status == InventoryAsset.Status.AVAILABLE


@pytest.mark.parametrize("owner", ["product", "box"])
@pytest.mark.parametrize("components", [
    [{"label": "Missing key", "quantity": 1}],
    [{"key": PRODUCT_KEY, "label": "Bad count", "quantity": 0}],
    [{"key": PRODUCT_KEY, "label": "String count", "quantity": "1"}],
    [{"key": PRODUCT_KEY.upper(), "label": "Noncanonical key", "quantity": 1}],
    [{"key": PRODUCT_KEY, "label": "Repeated", "quantity": 1}] * 2,
    [{"key": "invalid", "label": "Bad key", "quantity": 1}],
    [{"key": PRODUCT_KEY, "label": "Foreign reference", "quantity": 1, "product_id": 123}],
])
def test_control_panel_model_validation_refuses_invalid_kit_definitions(owner, components):
    from django.core.exceptions import ValidationError
    data = kit_setup()
    row = getattr(data, owner)
    row.kit_components = components
    with pytest.raises(ValidationError) as error:
        row.full_clean()
    assert "kit_components" in error.value.message_dict
