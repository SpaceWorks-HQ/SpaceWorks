from collections import Counter
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.evidence.finalization import charge_storage_once
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.hardware_requests.direct_loan_audit import record_item_logs
from apps.hardware_requests.direct_loan_returns import return_direct_loan, validate_evidence_upload
from apps.hardware_requests.self_checkout_workflow import (
    _checkout_target,
    _issue_product,
    _issued_request,
    qr_has_active_loan,
)
from apps.hardware_requests.workflow_errors import (
    InvalidTransition,
    RequestValidationError,
)
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.presence.guard import require_active_member_presence


def issue_direct_loan(
    makerspace,
    actor,
    *,
    borrower,
    evidence_id,
    remark,
    qr_payloads,
    items,
    container_id=None,
):
    require_active_member_presence(borrower, makerspace)
    evidence = EvidencePhoto.objects.filter(
        pk=evidence_id,
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
    ).first()
    if evidence is None:
        raise RequestValidationError("Invalid issue evidence.")
    if container_id is None and not qr_payloads and not items:
        raise RequestValidationError("Provide qr_payloads, items, or a container.")
    finalized = validate_evidence_upload(evidence, label="Issue")
    due_at = timezone.now() + timedelta(days=(makerspace.default_loan_days or 7))
    with transaction.atomic():
        EvidencePhoto.objects.select_for_update().get(pk=evidence.pk)
        if HardwareRequest.objects.filter(issue_evidence=evidence).exists():
            raise RequestValidationError("Evidence already used.")
        charge_storage_once(evidence, finalized.size)
        container = None
        if container_id is not None:
            container = (
                Box.objects.select_for_update()
                .filter(pk=container_id, makerspace=makerspace)
                .first()
            )
            if container is None:
                raise RequestValidationError("Container is not in this makerspace.")
            if not container.is_active:
                raise RequestValidationError("Container is not active.")
            # A physical container can only be out on one active handout at a time.
            # Explicit check gives a clean 409; the partial-unique constraint is the
            # race backstop (mirrors the per-QR active-loan guard).
            if PublicToolLoan.objects.filter(
                makerspace=makerspace,
                container=container,
                status=PublicToolLoan.Status.CHECKED_OUT,
            ).exists():
                raise InvalidTransition(
                    "That container is already out on another direct handout."
                )

        # A container-only handout (no QRs, no items) assigns an EMPTY vessel. If the box
        # - OR any child box nested under it - still holds available contents, a
        # container-only loan would walk them out the door while leaving them logically
        # AVAILABLE (re-loanable) - so reject and make staff hand out the contents (scan
        # the box QR) or empty it first.
        if container is not None and not qr_payloads and not items:
            subtree_ids = _container_subtree_ids(makerspace, container)
            has_contents = (
                InventoryProduct.objects.filter(
                    box_id__in=subtree_ids, is_archived=False, available_quantity__gt=0
                ).exists()
                or InventoryAsset.objects.filter(
                    box_id__in=subtree_ids, status=InventoryAsset.Status.AVAILABLE
                ).exists()
            )
            if has_contents:
                raise RequestValidationError(
                    "Container is not empty. Scan the box QR to hand out its contents, "
                    "or empty the container before assigning it on its own."
                )

        requester = borrower
        product_quantities = Counter()
        asset_ids = []
        labels = []
        qrs = _locked_qrs_for_payloads(makerspace, qr_payloads)
        loan_container = container

        seen_qr_ids = set()
        for qr in qrs:
            if qr.id in seen_qr_ids:
                # Same physical QR scanned twice in one handout would decrement
                # stock twice for one item; reject before any mutation.
                raise InvalidTransition("The same QR code was scanned more than once.")
            seen_qr_ids.add(qr.id)
            if qr.target_type == QrCode.TargetType.BOX and container is not None:
                if container.id != qr.target_id:
                    raise InvalidTransition("Scanned box does not match the selected container.")
            if qr_has_active_loan(makerspace, qr):
                raise InvalidTransition("One scanned QR code is already checked out.")
            label, quantities, target_asset_ids, target_container = _checkout_target(
                qr, require_public=False
            )
            if target_container is not None:
                if loan_container is None:
                    loan_container = target_container
                elif loan_container.id != target_container.id:
                    raise InvalidTransition("Only one handout container can be checked out at a time.")
            labels.append(label)
            product_quantities.update(quantities)
            asset_ids.extend(target_asset_ids)

        for item in items:
            product = _manual_product(makerspace, item["product_id"])
            quantity = item["quantity"]
            _issue_product(product, quantity)
            product_quantities[product] += quantity
            labels.append(product.name)

        request = _issued_request(
            makerspace,
            requester,
            requester.username,
            dict(product_quantities),
            requester_name=requester.display_name,
            contact_email=requester.email,
            contact_phone=requester.phone,
            return_due_at=due_at,
            requested_for="Admin direct handout",
            issued_by=actor,
        )
        request.issue_evidence = evidence
        request.issue_remark = str(remark or "").strip()
        request.save(update_fields=["issue_evidence", "issue_remark", "updated_at"])
        audit.record(
            actor,
            "evidence.attached",
            makerspace=makerspace,
            target=request,
            meta={"evidence_id": evidence.id, "type": evidence.evidence_type, "stage": "issue"},
        )
        try:
            with transaction.atomic():
                loan = PublicToolLoan.objects.create(
                    makerspace=makerspace,
                    qr_code=qrs[0] if qrs else None,
                    container=loan_container,
                    qr_ids=[qr.id for qr in qrs],
                    request=request,
                    requester=requester,
                    target_type="direct",
                    target_id=request.id,
                    target_label=", ".join(labels)[:200]
                    or (loan_container.label if loan_container else "Direct handout"),
                    asset_ids=asset_ids,
                    source=PublicToolLoan.Source.ADMIN_DIRECT,
                    due_at=due_at,
                )
        except IntegrityError as exc:
            raise InvalidTransition(
                "That container is already out on another direct handout."
            ) from exc
        for qr in qrs:
            QrScanEvent.objects.create(
                makerspace=makerspace,
                qr_code=qr,
                actor=actor,
                context=QrScanEvent.Context.ISSUE,
                request=request,
            )
        record_item_logs(actor, "admin_direct.checked_out", makerspace, request, loan)
        return loan


def _locked_qrs_for_payloads(makerspace, payloads):
    if not payloads:
        return []

    unique_payloads = set(payloads)
    qrs_by_payload = {
        qr.payload: qr
        for qr in QrCode.objects.select_for_update()
        .filter(
            payload__in=unique_payloads,
            makerspace=makerspace,
            status=QrCode.Status.ACTIVE,
        )
        .order_by("pk")
    }
    if len(qrs_by_payload) != len(unique_payloads):
        raise RequestValidationError("QR code is not active for this makerspace.")
    return [qrs_by_payload[payload] for payload in payloads]


def _container_subtree_ids(makerspace, container):
    # Walk Box.parent children iteratively (Box.clean() forbids same-makerspace cycles,
    # so this terminates) to collect the container + every descendant box id, so the
    # empty-container guard sees contents nested in child boxes too.
    ids = [container.id]
    frontier = [container.id]
    while frontier:
        child_ids = list(
            Box.objects.filter(parent_id__in=frontier, makerspace=makerspace)
            .exclude(pk__in=ids)
            .values_list("id", flat=True)
        )
        if not child_ids:
            break
        ids.extend(child_ids)
        frontier = child_ids
    return ids


def _manual_product(makerspace, product_id):
    product = InventoryProduct.objects.select_for_update().filter(
        pk=product_id,
        makerspace=makerspace,
        is_archived=False,
    ).first()
    if product is None:
        raise RequestValidationError(
            "Manual product is not in this makerspace or is archived."
        )
    if product.tracking_mode == TrackingMode.INDIVIDUAL:
        raise RequestValidationError(
            "Individual-tracked products require scanned asset QR codes for handout."
        )
    return product
