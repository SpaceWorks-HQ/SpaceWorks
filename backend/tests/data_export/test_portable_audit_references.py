import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models_claim import MemberClaimCode
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.hardware_requests.request_workflow import accept_request
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import MakerspaceMembership
from tests.encryption.conftest import enabled_encryption
from tests.data_export.portable_helpers import (
    archive_files,
    csv_rows,
    make_job,
    make_space,
    make_user,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _provenance(files):
    return [
        json.loads(line)
        for line in files["migration/reference_provenance.jsonl"].splitlines()
    ]


def _product(makerspace):
    return InventoryProduct.objects.create(
        makerspace=makerspace,
        name="Audit target product",
        total_quantity=3,
        available_quantity=3,
    )


def test_exported_audit_target_keeps_a_remappable_pair():
    actor = make_user("audit-exported-target")
    makerspace = make_space("audit-exported-target")
    product = _product(makerspace)
    log = audit.record(
        actor, "inventory.audit_target_test", makerspace=makerspace, target=product
    )

    files, _archive_bytes, _manifest = archive_files(make_job(makerspace, actor))

    row = next(item for item in csv_rows(files, "audit/audit_log.csv") if item["id"] == str(log.pk))
    assert row["target_type"] == "inventory.inventoryproduct"
    assert row["target_id"] == str(product.pk)
    assert not [item for item in _provenance(files) if item["source_object_id"] == str(log.pk)]


def test_non_bindable_audit_targets_are_cleared_with_typed_provenance():
    actor = make_user("audit-inert-target")
    target_user = make_user("audit-inert-user-target")
    makerspace = make_space("audit-inert-target")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=actor,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    claim = MemberClaimCode.objects.create(
        membership=membership,
        code_digest="f" * 64,
        issued_by=actor,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    user_log = audit.record(
        actor, "audit.user_target", makerspace=makerspace, target=target_user
    )
    omitted_log = audit.record(
        actor, "audit.omitted_target", makerspace=makerspace, target=claim
    )
    custom_log = AuditLog.objects.create(
        actor=actor,
        action="audit.custom_target",
        makerspace=makerspace,
        target_type="custom.Widget",
        target_id="8675309",
    )

    files, _archive_bytes, _manifest = archive_files(make_job(makerspace, actor))

    rows = {row["id"]: row for row in csv_rows(files, "audit/audit_log.csv")}
    for log in (user_log, omitted_log, custom_log):
        assert rows[str(log.pk)]["target_type"] == ""
        assert rows[str(log.pk)]["target_id"] == ""
    records = {
        item["source_object_id"]: item
        for item in _provenance(files)
        if item["field_name"] == "target_type+target_id"
    }
    assert records[str(user_log.pk)]["kind"] == "audit_user_target"
    assert records[str(omitted_log.pk)]["kind"] == "audit_omitted_target_model"
    assert records[str(custom_log.pk)]["kind"] == "audit_unrecognised_or_dropped_target"
    assert records[str(custom_log.pk)]["detail"]["source_target_id"] == "8675309"


def test_workflow_dictionary_key_ids_follow_the_declared_pk_map():
    actor = make_user("audit-dict-key-actor")
    requester = make_user("audit-dict-key-requester")
    makerspace = make_space("audit-dict-key")
    product = _product(makerspace)
    # HardwareRequest is a scoped-PII model, so this fixture must be built with
    # encryption on: a PORTABLE export deliberately refuses a plaintext mapped column.
    with enabled_encryption():
        request = HardwareRequest.objects.create(
            makerspace=makerspace,
            requester=requester,
            requester_username=requester.username,
            status=HardwareRequest.Status.PENDING_APPROVAL,
        )
        item = HardwareRequestItem.objects.create(
            request=request,
            product=product,
            requested_quantity=2,
        )

        accept_request(actor, request, {item.pk: 1})
        files, _archive_bytes, _manifest = archive_files(make_job(makerspace, actor))

    row = next(
        row
        for row in csv_rows(files, "audit/audit_log.csv")
        if row["action"] == "request.accepted"
    )
    assert json.loads(row["meta"])["accepted"] == {str(item.pk): 1}
    assert "source:" not in row["meta"]


def _deleted_presign(makerspace, actor, *, with_cleanup_audit):
    from django.db import connection, transaction

    from apps.evidence.models import EvidenceAbandonedUploadReceipt, EvidencePhoto

    photo = EvidencePhoto.objects.create(
        makerspace=makerspace, evidence_type="issue",
        object_key=f"evidence/{makerspace.pk}/issue/cleaned", uploaded_by=actor,
        consumption_state="unconsumed",
    )
    issued = audit.record(actor, "evidence.upload_url_issued", makerspace=makerspace, target=photo)
    with transaction.atomic():
        EvidenceAbandonedUploadReceipt.objects.create(
            source_makerspace_id_snapshot=makerspace.pk, evidence_id_snapshot=photo.pk,
            object_key=photo.object_key, next_reconcile_at=timezone.now(),
        )
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.evidence_abandoned_delete_id = %s", [str(photo.pk)])
        EvidencePhoto.objects.filter(pk=photo.pk).delete()
    if with_cleanup_audit:
        audit.record(
            None, "evidence.abandoned_upload_deleted", makerspace=makerspace,
            target=makerspace, meta={"evidence_id": photo.pk, "sweep_run_id": "run"},
        )
    return photo.pk, issued


def test_cleanup_proven_missing_evidence_target_becomes_inert_provenance():
    actor = make_user("audit-cleaned-evidence")
    makerspace = make_space("audit-cleaned-evidence")
    photo_id, issued = _deleted_presign(makerspace, actor, with_cleanup_audit=True)

    files, _archive_bytes, _manifest = archive_files(make_job(makerspace, actor))

    rows = {item["id"]: item for item in csv_rows(files, "audit/audit_log.csv")}
    assert (rows[str(issued.pk)]["target_type"], rows[str(issued.pk)]["target_id"]) == ("", "")
    provenance = [
        item for item in _provenance(files) if item["source_object_id"] == str(issued.pk)
    ]
    assert provenance and provenance[0]["kind"] == "audit_cleaned_abandoned_upload_target"
    assert provenance[0]["detail"]["source_target_id"] == str(photo_id)
    cleanup = next(
        item for item in rows.values() if item["meta"] and "sweep_run_id" in item["meta"]
    )
    assert json.loads(cleanup["meta"])["evidence_id"] == f"source:{photo_id}"


def test_missing_evidence_target_without_cleanup_proof_fails_closed():
    from apps.data_export.errors import ExportIntegrityError

    actor = make_user("audit-unproved-evidence")
    makerspace = make_space("audit-unproved-evidence")
    _deleted_presign(makerspace, actor, with_cleanup_audit=False)

    with pytest.raises(ExportIntegrityError, match="without a cleanup record"):
        archive_files(make_job(makerspace, actor))


def test_undeclared_id_bearing_meta_is_source_namespaced_at_export():
    actor = make_user("audit-safe-default")
    makerspace = make_space("audit-safe-default")
    product = _product(makerspace)
    log = AuditLog.objects.create(
        actor=actor,
        action="legacy.dynamic_action",
        makerspace=makerspace,
        meta={"future_id": product.pk, "indexed": {product.pk: "snapshot"}},
    )

    files, _archive_bytes, _manifest = archive_files(make_job(makerspace, actor))

    row = next(
        item
        for item in csv_rows(files, "audit/audit_log.csv")
        if item["id"] == str(log.pk)
    )
    assert json.loads(row["meta"]) == {
        "future_id": f"source:{product.pk}",
        "indexed": {f"source:{product.pk}": "snapshot"},
    }
