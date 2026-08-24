"""Lane E section 11 row 16: all-slice and post-seal verification."""

from pathlib import Path
from types import SimpleNamespace
import hashlib

import pytest

from apps.backup import compound_archive
from apps.backup.recipient_selection import BackupBuildError


def test_project_reconstructs_with_every_unsealed_slice_before_any_slice_is_sealed(
    monkeypatch, tmp_path
):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "database.dump").write_bytes(b"source dump")
    capture = compound_archive.CompoundCapture(
        archive=SimpleNamespace(pk="artifact"),
        root=root,
        modes={},
        platform_recipients=(),
    )
    frozen = (
        SimpleNamespace(makerspace_id=41),
        SimpleNamespace(makerspace_id=42),
    )
    unsealed = tuple(
        SimpleNamespace(frozen=item, plaintext=tmp_path / f"slice-{item.makerspace_id}")
        for item in frozen
    )
    capture.frozen_slices = frozen
    capture.unsealed_slices = list(unsealed)
    capture.verified_makerspace_ids = {41, 42}
    capture.expected_main_ledger = {"main": "expected"}
    capture.expected_full_ledger = {"full": "expected"}
    capture.reservation_capture = SimpleNamespace(sequence_facts=())
    capture.object_plan = SimpleNamespace(
        verify_component=lambda *_args: None
    )
    events = []

    def project(_source, destination, *_args, **_kwargs):
        destination.write_bytes(b"verified readable main")

    def reconstruct(_main, slices, *_args, **_kwargs):
        assert tuple(slices) == unsealed
        events.append("all-slice-reconstruction")
        return SimpleNamespace()

    def seal(item, *_args):
        events.append(f"seal-{item.frozen.makerspace_id}")
        return {"makerspace_id": item.frozen.makerspace_id}

    monkeypatch.setattr(compound_archive, "project_readable_main_dump", project)
    monkeypatch.setattr(compound_archive, "verify_reconstruction", reconstruct)
    monkeypatch.setattr(compound_archive, "seal_verified_slice", seal)
    monkeypatch.setattr(compound_archive, "table_rules", lambda: ())
    monkeypatch.setattr(compound_archive, "server_major", lambda: 16)
    monkeypatch.setattr(
        compound_archive,
        "_verify_sealed_slices",
        lambda *_args: events.append("post-seal-digests"),
    )
    monkeypatch.setattr(
        compound_archive,
        "verify_and_sign_source_partition",
        lambda *_args, **_kwargs: events.append("signed-proof") or {"proof": True},
    )

    result = capture.project_readable_main({
        "covered_makerspace_ids": [41, 42, 99],
        "storage": {"objects": []},
    })

    assert result["covered_makerspace_ids"] == [99]
    assert result["excluded_makerspace_ids"] == [41, 42]
    assert events == [
        "all-slice-reconstruction",
        "seal-41",
        "seal-42",
        "post-seal-digests",
        "signed-proof",
    ]


def test_post_seal_corruption_is_rejected_before_packaging(tmp_path):
    path = Path(tmp_path, "slices", "component.age")
    path.parent.mkdir()
    original = b"opaque sealed slice"
    path.write_bytes(original)
    entry = {
        "path": "slices/component.age",
        "size_bytes": len(original),
        "ciphertext_sha256": hashlib.sha256(original).hexdigest(),
    }
    path.write_bytes(b"substituted sealed slice")

    with pytest.raises(BackupBuildError, match="ciphertext verification"):
        compound_archive._verify_sealed_slices(tmp_path, (entry,))
