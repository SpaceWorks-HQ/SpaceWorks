"""Kiosk work packages and online command dispatch (phase 9b).

Every id is re-resolved inside the Station's makerspace -- never from the request
body -- and every mutation calls the existing workflow service with the lease User as
actor. No quantity math or transition logic lives here. One companion
``kiosk.online_command_executed`` row records the channel identity.
"""

from datetime import timedelta

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.audit import services as audit
from apps.boxes.models import QrCode, QrScanEvent
from apps.boxes.serializers import QrCodeSerializer, qr_target_payload
from apps.hardware_requests import direct_loan_workflow, workflow
from apps.hardware_requests.direct_loan_serializers import DirectLoanSerializer
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.self_checkout_models import PublicToolLoan
from apps.hardware_requests.serializers import AdminRequestSerializer

RESOLUTIONS = ["returned", "damaged", "missing"]
COMMAND_AGE_LIMIT_SECONDS = 15 * 60


def channel_meta(lease, kind, **extra):
    return {
        "station_id": lease.station_id,
        "station_session_id": str(lease.station_session_id),
        "station_version": lease.station_version,
        "operator_lease_id": str(lease.pk),
        "operation_kind": kind,
        **{key: value for key, value in extra.items() if value is not None},
    }


def _request(makerspace, pk):
    return get_object_or_404(HardwareRequest, pk=pk, makerspace=makerspace)


def _direct_loan(makerspace, pk):
    return get_object_or_404(
        PublicToolLoan, pk=pk, makerspace=makerspace,
        source=PublicToolLoan.Source.ADMIN_DIRECT,
    )


def _resolve_qr(makerspace, user, data):
    qr = get_object_or_404(
        QrCode, makerspace=makerspace, payload=data["payload"], status=QrCode.Status.ACTIVE,
    )
    if qr.target_type == QrCode.TargetType.MEMBER_CARD:
        # Identity never travels through the inventory scanner.
        raise Http404
    QrScanEvent.objects.create(
        makerspace=makerspace, qr_code=qr, actor=user,
        context=QrScanEvent.Context.SCANNER_LOOKUP,
    )
    return {"qr": QrCodeSerializer(qr).data, "target": qr_target_payload(qr)}, {}


def _assign_box(makerspace, user, data):
    updated = workflow.assign_box(user, _request(makerspace, data["request_id"]), data["box_code"])
    return AdminRequestSerializer(updated).data, {"request_id": updated.pk}


def _reviewed_issue(makerspace, user, data):
    updated = workflow.issue_request(
        user, _request(makerspace, data["request_id"]), data["evidence_id"], data["remark"],
        asset_qr_payloads=data["asset_qr_payloads"], rejects=data["rejects"],
    )
    return AdminRequestSerializer(updated).data, {
        "request_id": updated.pk, "evidence_id": data["evidence_id"],
    }


def _reviewed_return(makerspace, user, data):
    updated = workflow.return_items(
        user, _request(makerspace, data["request_id"]), data["evidence_id"],
        data["remark"], data["box_code"], data["resolutions"],
    )
    return AdminRequestSerializer(updated).data, {
        "request_id": updated.pk, "evidence_id": data["evidence_id"],
    }


def _direct_handout(makerspace, user, data):
    from apps.hardware_requests.direct_loan_views import _borrower_for_makerspace
    from apps.makerspaces.platform import module_enabled

    container_id = data.get("container_id")
    if container_id is not None and not module_enabled(makerspace, "containers"):
        container_id = None
    loan = direct_loan_workflow.issue_direct_loan(
        makerspace, user,
        borrower=_borrower_for_makerspace(makerspace, data["borrower_id"]),
        evidence_id=data["evidence_id"], remark=data.get("remark", ""),
        qr_payloads=data.get("qr_payloads") or [], items=data.get("items") or [],
        container_id=container_id,
    )
    return DirectLoanSerializer(loan).data, {
        "loan_id": loan.pk, "request_id": loan.request_id, "evidence_id": data["evidence_id"],
    }


def _direct_return(makerspace, user, data):
    returned = direct_loan_workflow.return_direct_loan(
        _direct_loan(makerspace, data["loan_id"]), user, data["evidence_id"],
        data["notes"], data["resolutions"], qr_payload=data.get("qr_payload", ""),
    )
    return DirectLoanSerializer(returned).data, {
        "loan_id": returned.pk, "evidence_id": data["evidence_id"],
    }


DISPATCH = {
    "resolve_qr": _resolve_qr,
    "assign_box": _assign_box,
    "reviewed_issue": _reviewed_issue,
    "reviewed_return": _reviewed_return,
    "direct_handout": _direct_handout,
    "direct_return": _direct_return,
}


def execute(*, station, lease, user, kind, payload):
    makerspace = station.makerspace
    result, refs = DISPATCH[kind](makerspace, user, payload)
    audit.record(
        user, "kiosk.online_command_executed", makerspace=makerspace, target=station,
        meta=channel_meta(lease, kind, **refs),
    )
    return result


def work_package(*, station, lease, user, kind, pk):
    makerspace = station.makerspace
    if kind == "reviewed_request":
        hardware_request = _request(makerspace, pk)
        box = hardware_request.assigned_box
        items = hardware_request.items.select_related("product").order_by("pk")
        data = {
            "status": hardware_request.status,
            "display_label": f"Request #{hardware_request.pk}",
            "person_display": hardware_request.requester_name or "",
            "box": box.label if box else None,
            "lines": [
                {"item_id": item.pk, "label": item.product.name,
                 "quantity": item.accepted_quantity, "returned": item.returned_quantity}
                for item in items[:100]
            ],
        }
        refs = {"request_id": hardware_request.pk}
    elif kind == "direct_handout":
        from apps.hardware_requests.direct_loan_views import _borrower_for_makerspace

        borrower = _borrower_for_makerspace(makerspace, pk)
        data = {
            "status": "prospective",
            "display_label": "New direct handout",
            "person_display": borrower.display_name or borrower.username,
            "box": None,
            "lines": [],
        }
        refs = {}
    else:
        loan = _direct_loan(makerspace, pk)
        requester = loan.requester
        data = {
            "status": loan.status,
            "display_label": f"Loan #{loan.pk}",
            "person_display": getattr(requester, "display_name", "") or "",
            "box": loan.container.label if loan.container_id else None,
            "lines": [],
        }
        refs = {"loan_id": loan.pk, "request_id": loan.request_id}
    audit.record(
        user, "kiosk.work_package_issued", makerspace=makerspace, target=station,
        meta=channel_meta(lease, kind, **refs),
    )
    return {
        "kind": kind, "id": pk, **data,
        "return_resolutions": RESOLUTIONS,
        "expires_at": min(lease.expires_at, timezone.now() + timedelta(hours=1)),
        "command_age_limit_seconds": COMMAND_AGE_LIMIT_SECONDS,
        "evidence_max_bytes": settings.EVIDENCE_MAX_BYTES,
    }
