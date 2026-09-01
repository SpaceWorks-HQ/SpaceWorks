import hashlib

import pytest

from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup.main_projection_inverse import boundary_deltas
from apps.backup.models import BackupArchive, RestoreOperation, RestoreRollbackObject
from apps.backup.object_ownership import (
    MAIN_COMPONENT,
    ObjectOwnershipPlan,
    ObjectReference,
    build_object_ownership_plan,
    slice_component,
)
from apps.backup.object_ownership_registry import ReferencePolicy
from apps.backup.recipient_selection import BackupBuildError
from apps.events.models import Event, EventRegistration
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db(transaction=True)


def _reference(key, *, owner=MAIN_COMPONENT, policy=""):
    return ObjectReference(
        bucket_kind="private",
        object_key=key,
        site=f"test.Model:1:object_key:{key}",
        candidate_owner=owner,
        canonical_makerspace_id=None,
        module_key="",
        coordination_policy=policy,
        coordination_makerspace_id=None,
    )


def _manifest(root, key, *, size=None, digest=None, owner=MAIN_COMPONENT):
    payload = (root / "private" / key).read_bytes()
    return [{
        "bucket_kind": "private",
        "key": key,
        "canonical_component": owner,
        "size": len(payload) if size is None else size,
        "sha256": hashlib.sha256(payload).hexdigest() if digest is None else digest,
    }]


def test_typed_references_equal_row_fields_and_cross_tenant_deltas():
    sovereign = Makerspace.objects.create(
        name="E4 sovereign", slug="e4-sovereign", superadmin_access_enabled=False
    )
    ordinary = Makerspace.objects.create(name="E4 ordinary", slug="e4-ordinary")
    sliced = InventoryProduct.objects.create(
        makerspace=sovereign, name="Sliced", image_key="e4/sliced.png"
    )
    retained = InventoryProduct.objects.create(
        makerspace=ordinary, name="Retained", image_key="e4/retained.png"
    )
    AuditLog.objects.create(
        action="machine.document_added",
        makerspace=sovereign,
        meta={"document_id": 91, "object_key": "e4/audit-only.pdf"},
    )
    event = Event.objects.create(
        makerspace=ordinary,
        title="Cross boundary",
        starts_at=timezone.now(),
        ends_at=timezone.now() + timezone.timedelta(hours=1),
    )
    registration = EventRegistration.objects.create(
        event=event,
        name="Boundary attendee",
        registered_via_makerspace=sovereign,
        payment_via_makerspace=sovereign,
    )

    plan = build_object_ownership_plan((sovereign.pk,))

    sliced_ref = plan.multimap[("public_image", sliced.image_key)]
    retained_ref = plan.multimap[("public_image", retained.image_key)]
    audit_ref = plan.multimap[("private", "e4/audit-only.pdf")]
    assert {item.site for item in sliced_ref} == {
        f"inventory.InventoryProduct:{sliced.pk}:image_key"
    }
    assert {item.candidate_owner for item in sliced_ref} == {
        slice_component(sovereign.pk)
    }
    assert {item.candidate_owner for item in retained_ref} == {MAIN_COMPONENT}
    assert audit_ref[0].candidate_owner is None
    assert audit_ref[0].coordination_policy == "audit_history_reference"
    assert "e4/audit-only.pdf" not in plan.closure(MAIN_COMPONENT)["private"]

    deltas = boundary_deltas(sovereign.pk)
    restored = {
        item["field"]: item["field_preimage"]
        for item in deltas
        if item["model"] == "events.EventRegistration"
        and item["row_pk"] == registration.pk
    }
    assert restored == {
        "registered_via_makerspace": sovereign.pk,
        "payment_via_makerspace": sovereign.pk,
    }


def test_two_component_candidates_for_one_physical_byte_refuse():
    sovereign = Makerspace.objects.create(
        name="E4 shared sovereign",
        slug="e4-shared-sovereign",
        superadmin_access_enabled=False,
    )
    ordinary = Makerspace.objects.create(
        name="E4 shared ordinary", slug="e4-shared-ordinary"
    )
    for space, name in ((sovereign, "Sliced"), (ordinary, "Main")):
        InventoryProduct.objects.create(
            makerspace=space, name=name, image_key="e4/shared-byte.png"
        )

    with pytest.raises(BackupBuildError, match="more than one canonical"):
        build_object_ownership_plan((sovereign.pk,))


def test_copy_key_bucket_is_resolved_from_each_row():
    space = Makerspace.objects.create(name="E4 rollback", slug="e4-rollback")
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        object_key="backup-archives/deployment/e4-source.tar.age",
        expires_at=timezone.now() + timezone.timedelta(days=1),
    )
    restore = RestoreOperation.objects.create(
        archive=archive, kind=RestoreOperation.Kind.ROLLBACK_IN_PLACE
    )
    row = RestoreRollbackObject.objects.create(
        restore=restore,
        makerspace=space,
        bucket_kind=RestoreRollbackObject.BucketKind.PRIVATE,
        source_key="source-key",
        copy_key="rollback/e4/copy",
        expires_at=timezone.now() + timezone.timedelta(days=1),
    )

    private_plan = build_object_ownership_plan(())
    assert ("private", row.copy_key) in private_plan.multimap
    assert ("public_image", row.copy_key) not in private_plan.multimap

    RestoreRollbackObject.objects.filter(pk=row.pk).update(
        bucket_kind=RestoreRollbackObject.BucketKind.PUBLIC_IMAGE
    )
    public_plan = build_object_ownership_plan(())
    assert ("public_image", row.copy_key) in public_plan.multimap
    assert ("private", row.copy_key) not in public_plan.multimap


def test_unknown_audit_object_variant_refuses_instead_of_json_guessing():
    space = Makerspace.objects.create(name="E4 audit", slug="e4-audit")
    AuditLog.objects.create(
        makerspace=space,
        action="future.object_variant",
        meta={"object_key": "future/unknown.bin"},
    )

    with pytest.raises(BackupBuildError, match="undeclared object-reference variant"):
        build_object_ownership_plan(())


@pytest.mark.parametrize(
    ("size", "digest"),
    ((999, None), (None, "0" * 64)),
)
def test_packaged_byte_must_match_immutable_size_and_digest(
    tmp_path, size, digest
):
    key = "captured.bin"
    path = tmp_path / "private" / key
    path.parent.mkdir(parents=True)
    path.write_bytes(b"immutable E4 bytes")
    plan = ObjectOwnershipPlan((_reference(key),), ())

    with pytest.raises(BackupBuildError, match="immutable capture ledger"):
        plan.bind_component(
            MAIN_COMPONENT,
            tmp_path,
            _manifest(tmp_path, key, size=size, digest=digest),
        )


def test_manifest_object_requires_reference_or_exact_coordination_policy(tmp_path):
    key = "coordination.bin"
    path = tmp_path / "private" / key
    path.parent.mkdir(parents=True)
    path.write_bytes(b"coordination bytes")

    with pytest.raises(BackupBuildError, match="manifest closure differ"):
        ObjectOwnershipPlan((), ()).bind_component(
            MAIN_COMPONENT, tmp_path, _manifest(tmp_path, key)
        )

    allowed = ObjectOwnershipPlan((
        _reference(
            key,
            owner=None,
            policy=ReferencePolicy.PACKAGE_MAIN_COORDINATION,
        ),
    ), ())
    allowed.bind_component(
        MAIN_COMPONENT, tmp_path, _manifest(tmp_path, key)
    )
    allowed.assert_complete()


def test_manifest_cannot_change_after_capture(tmp_path):
    key = "bound.bin"
    path = tmp_path / "private" / key
    path.parent.mkdir(parents=True)
    path.write_bytes(b"bound bytes")
    plan = ObjectOwnershipPlan((_reference(key),), ())
    manifest = _manifest(tmp_path, key)
    plan.bind_component(MAIN_COMPONENT, tmp_path, manifest)
    manifest[0]["sha256"] = "f" * 64

    with pytest.raises(BackupBuildError, match="immutable capture ledger"):
        plan.verify_component(MAIN_COMPONENT, manifest)
