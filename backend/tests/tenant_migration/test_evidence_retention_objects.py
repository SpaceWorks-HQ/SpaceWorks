from pathlib import Path

import pytest

from apps.tenant_migration.object_import import _validate_record
from apps.tenant_migration.insertion_errors import ArchiveFormatError
from apps.tenant_migration.tenant_dump_objects import package_staged_objects


def tombstone():
    return {
        "bucket_kind": "private",
        "source_key": "evidence/1/photo.jpg",
        "size": 0,
        "sha256": "",
        "version_id": None,
        "content_type": "",
        "retention_state": "expired",
        "object_expired_at": "2026-09-02T10:00:00+00:00",
        "expired_size_bytes": 789,
    }


def test_portable_manifest_accepts_only_a_complete_expiry_tombstone():
    _validate_record(tombstone(), 1)
    incomplete = tombstone()
    incomplete.pop("object_expired_at")

    with pytest.raises(ArchiveFormatError, match="Incomplete expiry tombstone"):
        _validate_record(incomplete, 1)


def test_lane_d_tombstone_packages_without_object_bytes(tmp_path):
    entry = {
        **tombstone(),
        "original_key": "evidence/1/photo.jpg",
        "member_path": None,
    }

    manifest = package_staged_objects(tmp_path / "capture", tmp_path / "bundle", [entry])

    assert manifest == ({
        "bucket_kind": "private",
        "member_path": None,
        "original_key": "evidence/1/photo.jpg",
        "version_id": None,
        "size": 0,
        "content_type": "",
        "sha256": "",
        "retention_state": "expired",
        "object_expired_at": "2026-09-02T10:00:00+00:00",
        "expired_size_bytes": 789,
    },)
    assert not Path(tmp_path / "bundle" / "objects").exists()
