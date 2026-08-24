"""Lane E section 11 row 18: reversed dependencies without plaintext retention."""

from io import BytesIO
import uuid

import pytest

from apps.backup import slice_merge
from apps.backup.models import B1RestoreComponentState
from apps.backup.slice_merge_types import SliceMergeInput
from tests.backup.test_slice_merge_crash_e8 import _patch_pipeline, _state


pytestmark = pytest.mark.django_db(transaction=True)


def test_dependency_wait_then_reversed_group_merge_retains_no_plaintext(
    monkeypatch, tmp_path
):
    operation, first, _reservation = _state()
    second = B1RestoreComponentState.objects.create(
        operation_id=operation.operation_id,
        artifact_id=operation.artifact_id,
        capture_id=operation.capture_id,
        component_id=uuid.uuid4(),
        makerspace_id_snapshot=880018,
        ciphertext_sha256="8" * 64,
        state=B1RestoreComponentState.State.PENDING,
    )
    _patch_pipeline(monkeypatch)
    plaintext = b"e10-decrypted-slice-must-not-survive"

    def decrypt(_ciphertext, plain_tar, _identity):
        plain_tar.write_bytes(plaintext)

    def extract(_plain_tar, root):
        (root / "tenant-plaintext.json").write_bytes(plaintext)

    def dependencies(_root, component, _manifest):
        if component.component_id == first.component_id:
            return [{
                "component_id": str(second.component_id),
                "reason": "declared_external_reference",
            }]
        return []

    monkeypatch.setattr(slice_merge, "decrypt_file", decrypt)
    monkeypatch.setattr(slice_merge, "extract_slice", extract)
    monkeypatch.setattr(slice_merge, "dependency_facts", dependencies)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    first_ciphertext = tmp_path / "first.age"
    second_ciphertext = tmp_path / "second.age"
    first_ciphertext.write_bytes(b"opaque-one")
    second_ciphertext.write_bytes(b"opaque-two")
    journal = tmp_path / "merge.journal"

    waiting = slice_merge.merge_slices(
        operation.operation_id,
        {},
        [SliceMergeInput(
            first.component_id, first_ciphertext, BytesIO(b"identity-one")
        )],
        journal_path=journal,
        scratch_parent=scratch,
    )
    assert waiting == {
        "state": "dependency_wait",
        "required_component_ids": [str(second.component_id)],
    }
    assert all(
        plaintext not in path.read_bytes()
        for path in tmp_path.rglob("*") if path.is_file()
    )
    assert not any(scratch.iterdir())

    restored = slice_merge.merge_slices(
        operation.operation_id,
        {},
        [
            SliceMergeInput(
                second.component_id, second_ciphertext, BytesIO(b"identity-two")
            ),
            SliceMergeInput(
                first.component_id, first_ciphertext, BytesIO(b"identity-one-retry")
            ),
        ],
        journal_path=journal,
        scratch_parent=scratch,
    )

    assert restored["state"] == "restored"
    assert set(restored["component_ids"]) == {
        str(first.component_id), str(second.component_id)
    }
    assert not any(scratch.iterdir())
    assert plaintext not in journal.read_bytes()
