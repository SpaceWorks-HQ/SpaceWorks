"""`create_final_from_staging` against the harness MinIO, not a fake client.

Every other promotion test mocks this primitive, which is how a version that handed a
non-seekable StreamingBody to `put_object` -- and so could never promote against a real
store -- went unnoticed.
"""

import hashlib
import uuid

import pytest
from django.conf import settings

from apps.backup import storage

pytestmark = pytest.mark.django_db


def _put(key, body):
    storage.client().put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key, Body=body)


def test_promotion_copies_staging_bytes_create_only_and_verifies():
    payload = uuid.uuid4().bytes * (300 * 1024)  # ~4.9 MB, several read chunks
    staging = f"backup-archives/staging/{uuid.uuid4()}.tar.age"
    final = f"backup-archives/deployment/{uuid.uuid4()}.tar.age"
    _put(staging, payload)

    storage.create_final_from_staging(staging, final)

    digest = hashlib.sha256(payload).hexdigest()
    assert storage.stream_verify(final, expected_size=len(payload), expected_sha256=digest) == (
        len(payload), digest,
    )


def test_promotion_never_overwrites_an_existing_final_locator():
    staging = f"backup-archives/staging/{uuid.uuid4()}.tar.age"
    final = f"backup-archives/deployment/{uuid.uuid4()}.tar.age"
    _put(staging, b"new bytes")
    _put(final, b"original bytes")

    with pytest.raises(storage.BackupStorageError, match="already exists"):
        storage.create_final_from_staging(staging, final)

    body = storage.client().get_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=final)["Body"]
    assert body.read() == b"original bytes"


def test_missing_staging_is_a_typed_storage_error():
    with pytest.raises(storage.BackupStorageError):
        storage.create_final_from_staging(
            f"backup-archives/staging/{uuid.uuid4()}.tar.age",
            f"backup-archives/deployment/{uuid.uuid4()}.tar.age",
        )
