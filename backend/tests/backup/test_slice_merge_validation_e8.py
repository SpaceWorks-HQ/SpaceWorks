from io import BytesIO
from types import SimpleNamespace
import hashlib
import uuid

import pytest

from apps.backup import slice_merge_identity, slice_merge_validation
from apps.backup.slice_merge_types import SliceMergeError


def _facts(tmp_path):
    ciphertext = tmp_path / "slice.age"
    ciphertext.write_bytes(b"opaque tenant slice")
    digest = hashlib.sha256(ciphertext.read_bytes()).hexdigest()
    operation = SimpleNamespace(
        operation_id=uuid.uuid4(), artifact_id=uuid.uuid4(), capture_id=uuid.uuid4(),
        outer_manifest_sha256="m" * 64,
    )
    component = SimpleNamespace(
        operation_id=operation.operation_id, artifact_id=operation.artifact_id,
        capture_id=operation.capture_id, component_id=uuid.uuid4(),
        makerspace_id_snapshot=77, ciphertext_sha256=digest,
    )
    manifest = {
        "artifact_id": str(operation.artifact_id),
        "capture_id": str(operation.capture_id),
        "slice_components": [{
            "component_id": str(component.component_id), "makerspace_id": 77,
            "size_bytes": ciphertext.stat().st_size, "ciphertext_sha256": digest,
            "recipient_fingerprints": ["f" * 64],
        }],
    }
    return operation, component, manifest, ciphertext


def test_bad_outer_signature_is_refused_before_other_component_checks(tmp_path, monkeypatch):
    operation, component, manifest, ciphertext = _facts(tmp_path)
    monkeypatch.setattr(
        slice_merge_validation,
        "verify_outer_manifest",
        lambda _value: (_ for _ in ()).throw(ValueError()),
    )

    with pytest.raises(SliceMergeError, match="signed outer manifest"):
        slice_merge_validation.validate_outer(operation, component, manifest, ciphertext, "f" * 64)


@pytest.mark.parametrize("mutation", ["artifact", "capture", "component"])
def test_each_outer_component_identity_binding_is_refused(tmp_path, monkeypatch, mutation):
    operation, component, manifest, ciphertext = _facts(tmp_path)
    monkeypatch.setattr(slice_merge_validation, "verify_outer_manifest", lambda _value: True)
    monkeypatch.setattr(slice_merge_validation, "manifest_digest", lambda _value: "m" * 64)
    if mutation == "artifact":
        manifest["artifact_id"] = str(uuid.uuid4())
    elif mutation == "capture":
        manifest["capture_id"] = str(uuid.uuid4())
    else:
        manifest["slice_components"][0]["component_id"] = str(uuid.uuid4())

    with pytest.raises(SliceMergeError, match="artifact, capture, or component"):
        slice_merge_validation.validate_outer(operation, component, manifest, ciphertext, "f" * 64)


def test_ciphertext_digest_and_stored_digest_are_each_refused(tmp_path, monkeypatch):
    operation, component, manifest, ciphertext = _facts(tmp_path)
    monkeypatch.setattr(slice_merge_validation, "verify_outer_manifest", lambda _value: True)
    monkeypatch.setattr(slice_merge_validation, "manifest_digest", lambda _value: "m" * 64)
    ciphertext.write_bytes(b"substituted")
    with pytest.raises(SliceMergeError, match="ciphertext digest"):
        slice_merge_validation.validate_outer(operation, component, manifest, ciphertext, "f" * 64)

    operation, component, manifest, ciphertext = _facts(tmp_path)
    component.ciphertext_sha256 = "0" * 64
    with pytest.raises(SliceMergeError, match="ciphertext digest"):
        slice_merge_validation.validate_outer(operation, component, manifest, ciphertext, "f" * 64)


def test_wrong_recipient_fingerprint_is_refused(tmp_path, monkeypatch):
    operation, component, manifest, ciphertext = _facts(tmp_path)
    monkeypatch.setattr(slice_merge_validation, "verify_outer_manifest", lambda _value: True)
    monkeypatch.setattr(slice_merge_validation, "manifest_digest", lambda _value: "m" * 64)
    with pytest.raises(SliceMergeError, match="recipient"):
        slice_merge_validation.validate_outer(operation, component, manifest, ciphertext, "0" * 64)


def test_identity_channel_is_consumed_closed_and_zeroizable():
    channel = BytesIO(b"AGE-SECRET-KEY-private-material")
    identity = slice_merge_identity.read_identity(channel)
    assert channel.closed
    assert bytes(identity).startswith(b"AGE-SECRET-KEY")
    slice_merge_identity.zeroize(identity)
    assert identity == bytearray(len(identity))
