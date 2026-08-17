import hashlib
import json
from pathlib import Path

from cryptography.fernet import Fernet
import pytest

from apps.evidence.models import EvidencePhoto
from apps.tenant_migration import object_storage
from apps.tenant_migration.deployment_keys import public_deployment_identity
from apps.tenant_migration.object_export import object_member_path
from apps.tenant_migration.pairing import approve_pairing
from apps.tenant_migration.receipt_crypto import ALGORITHM, generate_key_material
from tests.tenant_migration.protocol_helpers import signed_envelope


PRIVATE_KEY = "evidence/source/issue.jpg"
PUBLIC_KEY = "makerspace/source/logo.png"
PRIVATE_BYTES = b"private evidence bytes"
PUBLIC_BYTES = b"public image bytes"


@pytest.fixture(autouse=True)
def encryption_key(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode("ascii")


@pytest.fixture
def memory_objects(monkeypatch):
    buckets = {"private": {}, "public_image": {}, "quota": []}
    monkeypatch.setattr(
        object_storage, "object_exists", lambda kind, key: key in buckets[kind]
    )
    monkeypatch.setattr(
        object_storage,
        "upload_staged",
        lambda key, path: buckets["private"].__setitem__(
            key, Path(path).read_bytes()
        ),
    )

    def digest(kind, key):
        data = buckets[kind][key]
        return len(data), hashlib.sha256(data).hexdigest()

    def copy(staging_key, kind, target_key):
        buckets[kind][target_key] = buckets["private"][staging_key]

    monkeypatch.setattr(object_storage, "digest_object", digest)
    monkeypatch.setattr(object_storage, "copy_from_staging", copy)
    monkeypatch.setattr(
        object_storage,
        "delete_object",
        lambda kind, key: buckets[kind].pop(key, None),
    )
    monkeypatch.setattr(
        object_storage,
        "list_staging_keys",
        lambda job_id: {
            key
            for key in buckets["private"]
            if key.startswith(f"tenant-imports/{job_id}/")
        },
    )
    monkeypatch.setattr(
        "apps.tenant_migration.object_import.limits.add_storage",
        lambda _space, size: buckets["quota"].append(("add", size)),
    )
    monkeypatch.setattr(
        "apps.tenant_migration.object_import.limits.free_storage",
        lambda _space, size: buckets["quota"].append(("free", size)),
    )
    return buckets


def prepare_source_objects(space, user, _request):
    space.logo_key = PUBLIC_KEY
    space.save(update_fields=("logo_key",))
    return EvidencePhoto.objects.create(
        makerspace=space,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=PRIVATE_KEY,
        content_type="image/jpeg",
        size_bytes=len(PRIVATE_BYTES),
        uploaded_by=user,
    )


def write_object_bundle(root):
    records = []
    for kind, key, data in (
        ("private", PRIVATE_KEY, PRIVATE_BYTES),
        ("public_image", PUBLIC_KEY, PUBLIC_BYTES),
    ):
        path = Path(root) / object_member_path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        records.append(
            {
                "bucket_kind": kind,
                "source_key": key,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "version_id": "source-version" if kind == "private" else None,
            }
        )
    Path(root, "objects", "manifest.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in records),
        encoding="utf-8",
    )


def pairing_and_receipt(job, actor):
    source_material = generate_key_material()
    source_identity = {
        "algorithm": ALGORITHM,
        "deployment_id": job.source_deployment_id,
        "public_key": source_material["public_key"],
        "fingerprint": source_material["fingerprint"],
    }
    pairing = approve_pairing(
        actor=actor,
        migration_id=job.pk,
        source_tenant_id=job.source_makerspace_id,
        archive_digest=job.source_archive_digest,
        source=source_identity,
        target=public_deployment_identity(),
    )
    receipt = signed_envelope(
        pairing,
        "source_cutover",
        source_identity,
        source_material["private_key"],
    )
    return pairing, receipt
