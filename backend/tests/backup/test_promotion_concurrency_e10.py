"""Lane E section 11 row 14: final-byte readback must finish before locks."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
import uuid

from apps.backup import artifact_protocol


def test_blocked_final_readback_prevents_promotion_from_reaching_lock_primitive(
    monkeypatch,
):
    final_read_started = Event()
    release_final_read = Event()
    promotion_called = Event()
    ledger = SimpleNamespace(
        artifact_id=uuid.uuid4(),
        staging_locator="backup-archives/staging/e10.tar.age",
        final_locator="backup-archives/deployment/e10.tar.age",
        expected_size_bytes=9,
        outer_sha256="a" * 64,
    )
    monkeypatch.setattr(
        artifact_protocol, "persist_pending", lambda *_args: ledger
    )
    monkeypatch.setattr(
        artifact_protocol.storage, "upload_staging", lambda *_args: None
    )
    monkeypatch.setattr(
        artifact_protocol.storage, "create_final_from_staging", lambda *_args: None
    )
    monkeypatch.setattr(
        artifact_protocol.storage, "delete_archive", lambda *_args: True
    )
    monkeypatch.setattr(
        artifact_protocol, "mark_staging_verified", lambda *_args: None
    )
    monkeypatch.setattr(
        artifact_protocol, "mark_final_verified", lambda *_args: None
    )
    monkeypatch.setattr(
        artifact_protocol, "mark_cleanup_complete", lambda *_args: None
    )

    def verify(key, **_kwargs):
        if key == ledger.final_locator:
            final_read_started.set()
            assert release_final_read.wait(10)
        return ledger.expected_size_bytes, ledger.outer_sha256

    def promote(_artifact_id):
        promotion_called.set()
        return "available"

    monkeypatch.setattr(artifact_protocol.storage, "stream_verify", verify)
    monkeypatch.setattr(artifact_protocol, "promote_verified_artifact", promote)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            artifact_protocol.upload_verify_and_promote,
            SimpleNamespace(),
            SimpleNamespace(encrypted="unused"),
            ledger.expected_size_bytes,
        )
        assert final_read_started.wait(10)
        assert not promotion_called.is_set()
        assert not future.done()
        release_final_read.set()
        assert future.result(timeout=10) == "available"

    assert promotion_called.is_set()
