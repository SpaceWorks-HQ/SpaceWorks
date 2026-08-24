from datetime import timedelta
import hashlib
import json
from types import SimpleNamespace
import uuid

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup.main_projection_registry import table_rules
from apps.backup.models import B1ReservationEntry
from apps.backup.outer_reservation_validation import _validate_fences
from apps.backup.reservation_catalog import IndexComponent, UniqueRule
from apps.backup.source_fences import (
    broad_unique_fence,
    object_namespace_fences,
    relationship_fences,
)
from apps.backup.source_reservations import ReservationCapture
from apps.events.models import Event, EventRegistration
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from tests.backup.e7_reservation_test_helpers import (
    assert_database_rejects,
    persist_active_reservation,
)


pytestmark = pytest.mark.django_db(transaction=True)


def _spaces():
    sovereign = Makerspace.objects.create(
        name="E7 opaque relationship", slug=f"e7-opaque-{uuid.uuid4().hex}",
        superadmin_access_enabled=False,
    )
    ordinary = Makerspace.objects.create(
        name="E7 readable relationship", slug=f"e7-readable-{uuid.uuid4().hex}"
    )
    return sovereign, ordinary


def _relationship_setup(*, persist_inbound=True):
    sovereign, ordinary = _spaces()
    event = Event.objects.create(
        makerspace=ordinary,
        title="E7 relationship fence",
        starts_at=timezone.now(),
        ends_at=timezone.now() + timedelta(hours=1),
    )
    baseline = EventRegistration.objects.create(
        event=event, name="Existing", email="existing-e7@example.test", phone=""
    )
    component_id = uuid.uuid4()
    facts = relationship_fences(
        "default", table_rules(), {sovereign.pk: component_id}
    )
    inbound = next(
        item for item in facts
        if item["table"] == EventRegistration._meta.db_table
        and "registered_via_makerspace_id" in item["columns"]
    )
    if persist_inbound:
        persist_active_reservation(
            inbound, B1ReservationEntry.Kind.RELATIONSHIP_FENCE,
            makerspace_id=sovereign.pk,
        )
    return sovereign, event, baseline, facts


@pytest.mark.parametrize("operation", ("create", "update", "delete"))
def test_relationship_fence_rejects_inbound_fk_create_update_and_delete(operation):
    sovereign, event, baseline, _facts = _relationship_setup()
    if operation == "create":
        write = lambda: EventRegistration.objects.create(
            event=event,
            name="New inbound",
            email="new-inbound-e7@example.test",
            phone="",
            registered_via_makerspace=sovereign,
        )
    elif operation == "update":
        write = lambda: EventRegistration.objects.filter(pk=baseline.pk).update(
            registered_via_makerspace=sovereign
        )
    else:
        write = lambda: EventRegistration.objects.filter(pk=baseline.pk).delete()

    assert_database_rejects(write)


def test_relationship_fence_rejects_semantic_reference_creation():
    sovereign, _event, _baseline, facts = _relationship_setup(
        persist_inbound=False
    )
    control = AuditLog.objects.create(
        action="e7.semantic.control", target_type="", target_id="", meta={}
    )
    assert control.pk is not None
    semantic = next(
        item for item in facts if item["dependency_kind"] == "semantic_reference"
    )
    assert semantic["operations"] == ["insert", "update", "delete"]
    persist_active_reservation(
        semantic, B1ReservationEntry.Kind.RELATIONSHIP_FENCE,
        makerspace_id=sovereign.pk,
    )

    assert_database_rejects(lambda: AuditLog.objects.create(
        action="e7.semantic.probe",
        target_type="makerspaces.Makerspace",
        target_id=str(sovereign.pk),
        meta={"makerspace_id": sovereign.pk},
    ))


def _object_setup():
    sovereign, _ordinary = _spaces()
    baseline = InventoryProduct.objects.create(
        makerspace=sovereign,
        name="E7 existing object",
        image_key="member-chosen/opaque/object-name.png",
        total_quantity=1,
    )
    component_id = uuid.uuid4()
    plan = SimpleNamespace(references=(SimpleNamespace(
        candidate_owner=f"slice:{sovereign.pk}",
        site=f"inventory.InventoryProduct:{baseline.pk}:image_key",
        bucket_kind="public_image",
        canonical_makerspace_id=sovereign.pk,
    ),))
    fact = object_namespace_fences(plan, {sovereign.pk: component_id})[0]
    persist_active_reservation(
        fact, B1ReservationEntry.Kind.OBJECT_NAMESPACE,
        makerspace_id=sovereign.pk,
    )
    return sovereign, baseline, fact


@pytest.mark.parametrize("operation", ("create", "overwrite", "delete"))
def test_object_namespace_fence_rejects_create_overwrite_and_delete(operation):
    sovereign, baseline, fact = _object_setup()
    assert fact["operations"] == ["insert", "update", "delete", "overwrite"]
    if operation == "create":
        write = lambda: InventoryProduct.objects.create(
            makerspace=sovereign,
            name="E7 new object",
            image_key="member-chosen/new-object.png",
            total_quantity=1,
        )
    elif operation == "overwrite":
        write = lambda: InventoryProduct.objects.filter(pk=baseline.pk).update(
            image_key="member-chosen/replacement.png"
        )
    else:
        write = lambda: InventoryProduct.objects.filter(pk=baseline.pk).delete()

    assert_database_rejects(write)


def test_low_entropy_manifest_facts_publish_no_enumerable_oracle():
    component_id = str(uuid.uuid4())
    secret = "short-and-enumerable-e7"
    component = IndexComponent(
        1, "slug", "slug", "pg_catalog.varchar:character varying(64)",
        "pg_catalog.varchar_ops", "pg_catalog.C", "c", True, "C", "", "",
    )
    rule = UniqueRule(
        "public", "makerspaces_makerspace", "e7_low_entropy", "index", "",
        "", False, False, False, False, (component,),
    )
    fence = broad_unique_fence(rule, [{"component_id": component_id, "count": 1}])
    capture = ReservationCapture(
        run_salt=b"s" * 32,
        registry_digest="a" * 64,
        commitments=(), broad_fences=(fence,), relationship_fences=(),
        object_namespace_fences=(), sequence_facts=(), rule_proofs=(),
        raw_keys_by_component={},
    )
    encoded = json.dumps(capture.manifest_facts(), sort_keys=True)
    assert secret not in encoded
    assert hashlib.sha256(secret.encode()).hexdigest() not in encoded
    assert set(fence) == {
        "version", "constraint_identity", "schema", "table", "columns",
        "operations", "component_ids", "definition_sha256",
    }
    _validate_fences([fence], {component_id}, "broad")

    oracle = {**fence, "per_value_digest": hashlib.sha256(secret.encode()).hexdigest()}
    with pytest.raises(ValueError):
        _validate_fences([oracle], {component_id}, "broad")
