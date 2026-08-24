"""Lane E section 11 row 1: assert the custody guarantee on real bytes."""

import json
from pathlib import Path
import subprocess
import tarfile
import uuid

import pytest
from django.contrib.auth import get_user_model

from apps.backup import archive_builder
from apps.backup.postgres_client import client_binary
from apps.hardware_requests.models import HardwareRequest
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from tests.backup import test_compound_archive_e3 as e3


pytestmark = pytest.mark.django_db(transaction=True)


def test_real_main_manifest_and_slice_bytes_enforce_the_custody_boundary(
    allow_projection_databases, monkeypatch, settings
):
    sovereign = e3._sovereign()
    ordinary = Makerspace.objects.create(
        name="E10 ordinary", slug=f"e10-ordinary-{uuid.uuid4().hex}"
    )
    requester = get_user_model().objects.create_user(
        username=f"e10-sovereign-{uuid.uuid4().hex}"
    )
    secret = f"tenant-plaintext-{uuid.uuid4().hex}"
    request = HardwareRequest.objects.create(
        makerspace=sovereign,
        requester=requester,
        requester_username=requester.username,
        requester_name=secret,
        requested_for="E10 byte guarantee",
    )
    InventoryProduct.objects.create(
        makerspace=ordinary,
        name="E10 readable marker",
        total_quantity=1,
    )
    raw_reservation = str(request.public_token).encode()
    tenant_plaintext = secret.encode()
    e3._prepare(monkeypatch, settings)

    encrypted, manifest, tempdir, _digest = archive_builder.build_archive(
        e3._archive()
    )
    try:
        root = Path(tempdir.name, "bundle")
        readable_main = subprocess.run(
            [client_binary("pg_restore"), "--file=-", str(root / "database.dump")],
            check=True,
            capture_output=True,
        ).stdout
        manifest_bytes = json.dumps(
            manifest, sort_keys=True, separators=(",", ":")
        ).encode()
        slice_fact = next(
            item for item in manifest["slice_components"]
            if item["makerspace_id"] == sovereign.pk
        )
        slice_bytes = (root / slice_fact["ciphertext_path"]).read_bytes()

        for forbidden in (tenant_plaintext, raw_reservation):
            assert forbidden not in readable_main
            assert forbidden not in manifest_bytes
            assert forbidden in slice_bytes

        assert str(sovereign.pk).encode() in manifest_bytes
        assert slice_fact["component_id"].encode() in manifest_bytes
        assert slice_fact["ciphertext_sha256"].encode() in manifest_bytes
        assert str(slice_fact["size_bytes"]).encode() in manifest_bytes

        with tarfile.open(encrypted) as outer:
            member = outer.extractfile(f"./{slice_fact['ciphertext_path']}")
            assert member is not None
            assert member.read() == slice_bytes
    finally:
        tempdir.cleanup()
