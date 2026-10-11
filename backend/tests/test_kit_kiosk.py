import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.hardware_requests.models import RequesterAccountability, ReturnEvent
from apps.hardware_requests.replay_failures import ReplayFailure
from apps.hardware_requests.replay_serializers import _bound_payload
from tests.hardware_requests.test_kiosk_online import command, kiosk_settings, leased
from tests.kit_helpers import BOX_KEY, PRODUCT_KEY, kit_setup
from tests.return_helpers import make_issue_evidence, make_return_evidence

pytestmark = pytest.mark.django_db
# Import the existing kiosk_settings autouse fixture so Station signing uses the
# same independent test keys and origin as the online kiosk regression suite.


def test_kiosk_work_packages_and_commands_keep_counts_and_user_actor():
    data = kit_setup(box_kit=True)
    data.space.enabled_features = [*data.space.enabled_features, "inventory.kiosk"]
    data.space.save(update_fields=["enabled_features"])
    client, token, headers, station = leased(data.space, data.actor)
    assigned = command(client, token, headers, "assign_box",
                       {"request_id": data.request.pk, "box_code": data.box.code})
    assert assigned.status_code == 200
    url = reverse("kiosk-station-work-package", kwargs={"public_token": token})
    work = client.post(url, {"kind": "reviewed_request", "id": data.request.pk}, format="json", **headers)
    assert work.status_code == 200
    assert {row["key"] for row in work.data["kit_components"]} == {PRODUCT_KEY, BOX_KEY}
    issued = command(client, token, headers, "reviewed_issue", {
        "request_id": data.request.pk, "evidence_id": make_issue_evidence(data.space, data.actor).pk,
        "kit_checklist": [{"key": PRODUCT_KEY, "present": 12}, {"key": BOX_KEY, "present": 1}],
    })
    assert issued.status_code == 200, issued.data
    data.product.kit_components = []
    data.product.save(update_fields=["kit_components"])
    return_work = client.post(url, {"kind": "reviewed_request", "id": data.request.pk}, format="json", **headers)
    assert return_work.data["kit_components"][0]["issue_present"] == 12
    returned = command(client, token, headers, "reviewed_return", {
        "request_id": data.request.pk, "evidence_id": make_return_evidence(data.space, data.actor).pk,
        "box_code": data.box.code, "remark": "Physically checked",
        "resolutions": [{"item_id": data.item.pk, "returned": 1}],
        "kit_checklist": [{"key": PRODUCT_KEY, "present": 11}, {"key": BOX_KEY, "present": 1}],
    })
    assert returned.status_code == 200, returned.data
    assert RequesterAccountability.objects.get(request=data.request).created_by == data.actor
    assert ReturnEvent.objects.get(request=data.request).actor == data.actor
    assert not AuditLog.objects.filter(makerspace=data.space, action__startswith="kit.").exclude(actor=data.actor).exists()
    assert AuditLog.objects.filter(action="kiosk.online_command_executed", actor=data.actor,
                                   meta__station_id=station["id"]).count() == 3


def test_replay_allows_bounded_multi_product_kits_without_widening_other_lists():
    _bound_payload({"kit_checklist": [{"key": PRODUCT_KEY, "present": 1}] * 101})
    with pytest.raises(ReplayFailure):
        _bound_payload({"kit_checklist": [0] * 3551})
    with pytest.raises(ReplayFailure):
        _bound_payload({"asset_qr_payloads": ["qr"] * 101})
