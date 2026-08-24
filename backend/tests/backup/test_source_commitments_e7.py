import base64
import json
import uuid

import pytest
from django.contrib.auth import get_user_model

from apps.backup.main_projection_registry import table_rules
from apps.backup.postgres_client import server_major
from apps.backup.reservation_catalog import load_unique_rules
from apps.backup.reservation_keys import reservation_commitment
from apps.backup.source_reservations import capture_source_reservations
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db(transaction=True)


def test_source_capture_publishes_one_bound_commitment_not_canonical_bytes():
    sovereign = Makerspace.objects.create(
        name="E7 source commitment",
        slug=f"e7-source-{uuid.uuid4().hex}",
        superadmin_access_enabled=False,
    )
    requester = get_user_model().objects.create_user(
        username=f"e7-source-{uuid.uuid4().hex}"
    )
    request = HardwareRequest.objects.create(
        makerspace=sovereign,
        requester=requester,
        requester_username=requester.username,
    )
    component_id = uuid.uuid4()
    mapping = {sovereign.pk: component_id}
    first = capture_source_reservations(
        "default", table_rules(), mapping, postgres_major=server_major()
    )
    second = capture_source_reservations(
        "default", table_rules(), mapping, postgres_major=server_major()
    )
    rule = next(
        item for item in load_unique_rules()
        if item.table == HardwareRequest._meta.db_table
        and item.components[0].source_column == "public_token"
    )
    published = next(
        item for item in first.commitments
        if item["constraint_identity"] == rule.identity
    )
    group = next(
        item for item in published["component_commitments"]
        if item["component_id"] == str(component_id)
    )
    raw_entries = [
        framed for identity, framed in first.raw_keys_by_component[str(component_id)]
        if identity == rule.identity
    ]

    assert len(group["commitments"]) == len(raw_entries) == 1
    assert group["commitments"][0] == reservation_commitment(
        first.run_salt, raw_entries[0]
    )
    assert first.run_salt != second.run_salt
    second_published = next(
        item for item in second.commitments
        if item["constraint_identity"] == rule.identity
    )
    assert second_published["component_commitments"][0]["commitments"] != (
        group["commitments"]
    )

    manifest_bytes = json.dumps(first.manifest_facts(), sort_keys=True).encode()
    assert str(request.public_token).encode() not in manifest_bytes
    assert request.public_token.bytes not in manifest_bytes
    assert base64.b64encode(raw_entries[0]) not in manifest_bytes
