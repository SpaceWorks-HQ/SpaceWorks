"""Promotion must bound memory and give botocore a rewindable body."""

import hashlib
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from apps.backup import storage, storage_promotion


class NonSeekableBody:
    def __init__(self, *, fail=False):
        self.remaining = storage_promotion.CHUNK_SIZE * 3 + 17
        self.size = self.remaining
        self.reads = []
        self.closed = False
        self.fail = fail

    def read(self, amount=-1):
        assert 0 < amount <= storage_promotion.CHUNK_SIZE
        self.reads.append(amount)
        if self.fail:
            raise OSError("source disconnected")
        size = min(self.remaining, amount)
        self.remaining -= size
        return b"x" * size

    def close(self):
        self.closed = True


def test_nonseekable_source_streams_in_bounded_chunks_to_a_rewindable_put(monkeypatch):
    source = NonSeekableBody()
    calls = []
    handles = []

    def get_object(**kwargs):
        calls.append(kwargs)
        return {"Body": source}

    def put_object(**kwargs):
        body = kwargs["Body"]
        handles.append(body)
        assert source.closed
        assert body.seekable() and body.tell() == 0
        assert kwargs["IfNoneMatch"] == "*"
        assert kwargs["Key"] == "immutable-final"
        assert kwargs["ContentLength"] == source.size
        # Model checksum/signature calculation followed by the real send.
        for _ in range(2):
            digest = hashlib.sha256()
            while chunk := body.read(storage_promotion.CHUNK_SIZE):
                digest.update(chunk)
            assert digest.hexdigest() == hashlib.sha256(b"x" * source.size).hexdigest()
            body.seek(0)

    monkeypatch.setattr(storage, "client", lambda: SimpleNamespace(
        get_object=get_object, put_object=put_object,
    ))

    storage.create_final_from_staging("staging-only", "immutable-final")

    assert calls == [{"Bucket": storage.settings.AWS_STORAGE_BUCKET_NAME, "Key": "staging-only"}]
    assert len(source.reads) == 5  # Three full chunks, tail, EOF.
    assert handles[0].closed


def test_stream_failure_closes_the_source_and_never_publishes(monkeypatch):
    source = NonSeekableBody(fail=True)
    puts = []
    monkeypatch.setattr(storage, "client", lambda: SimpleNamespace(
        get_object=lambda **kwargs: {"Body": source},
        put_object=lambda **kwargs: puts.append(kwargs),
    ))
    with pytest.raises(storage.BackupStorageError, match="could not be promoted"):
        storage.create_final_from_staging("stage", "final")
    assert source.closed
    assert puts == []


@pytest.mark.parametrize("status", [409, 412])
def test_conditional_conflict_is_typed_and_closes_both_streams(monkeypatch, status):
    source = NonSeekableBody()
    handles = []

    def reject(**kwargs):
        handles.append(kwargs["Body"])
        assert kwargs["IfNoneMatch"] == "*"
        raise ClientError({"Error": {"Code": "PreconditionFailed"},
                           "ResponseMetadata": {"HTTPStatusCode": status}}, "PutObject")

    monkeypatch.setattr(storage, "client", lambda: SimpleNamespace(
        get_object=lambda **kwargs: {"Body": source}, put_object=reject,
    ))
    with pytest.raises(storage.BackupStorageError, match="already exists"):
        storage.create_final_from_staging("stage", "final")
    assert source.closed and handles[0].closed
