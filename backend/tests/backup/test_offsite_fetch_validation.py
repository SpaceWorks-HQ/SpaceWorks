"""Malformed destination metadata must refuse cleanly before creating output."""

import json
from io import BytesIO, StringIO
from types import SimpleNamespace

import pytest
from django.core.management import CommandError, call_command

from apps.backup import offsite_client
from apps.backup.management.commands.fetch_offsite_archive import load_credentials_file
from apps.backup.offsite_push import enqueue_offsite_uploads, push_due_uploads
from tests.backup.offsite_test_support import (
    make_destination, offsite_bucket, stored_archive,  # noqa: F401
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("value", [[], None, "not-an-index", 42])
def test_non_object_index_is_a_typed_destination_error(monkeypatch, value):
    body = BytesIO(json.dumps(value).encode())
    monkeypatch.setattr(offsite_client, "open_remote", lambda *args: body)
    with pytest.raises(offsite_client.OffsiteDestinationError) as error:
        offsite_client.read_index(None, "bucket", "archive")
    assert error.value.code == "index_invalid"
    assert body.closed


def test_credentials_file_refuses_non_string_values(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"bucket": [], "access_key_id": "access", "secret_access_key": "secret"}))
    path.chmod(0o600)
    with pytest.raises(CommandError, match="must be a string"):
        load_credentials_file(path)


@pytest.mark.parametrize("size", ["bad", -1, 0, True, [], 2.5])
def test_invalid_sidecar_size_refuses_before_creating_a_local_archive(tmp_path, monkeypatch, size):
    from apps.backup.management.commands.fetch_offsite_archive import Command

    command = Command(stdout=StringIO())
    destination = SimpleNamespace(bucket="bucket")
    monkeypatch.setattr(offsite_client, "read_index", lambda *args: {"size_bytes": size, "sha256": "a" * 64})
    with pytest.raises(CommandError, match="positive integer"):
        command._expected(None, destination, "archive", "archive-id", None, None)


def test_fetch_never_replaces_an_existing_local_file(tmp_path, offsite_bucket):
    archive = stored_archive()
    destination = make_destination(offsite_bucket)
    enqueue_offsite_uploads()
    push_due_uploads()
    output = tmp_path / "existing.tar.age"
    output.write_bytes(b"preserve this file")
    with pytest.raises(CommandError, match="must not already exist"):
        call_command("fetch_offsite_archive", "--destination", destination.name,
                     "--archive-id", str(archive.pk), "--output", str(output), stdout=StringIO())
    assert output.read_bytes() == b"preserve this file"


def test_fetch_writes_a_private_local_index_of_the_verified_facts(tmp_path, offsite_bucket):
    import os

    archive = stored_archive()
    destination = make_destination(offsite_bucket)
    enqueue_offsite_uploads()
    push_due_uploads()
    output = tmp_path / "download.tar.age"
    call_command("fetch_offsite_archive", "--destination", destination.name,
                 "--archive-id", str(archive.pk), "--output", str(output), stdout=StringIO())
    index = tmp_path / "download.tar.age.index.json"
    assert json.loads(index.read_text()) == {
        "archive_id": str(archive.pk), "scope": "deployment",
        "size_bytes": archive.size_bytes, "sha256": archive.archive_sha256,
    }
    assert os.stat(index).st_mode & 0o777 == 0o600


def test_fetch_never_replaces_an_existing_local_index(tmp_path, offsite_bucket):
    archive = stored_archive()
    destination = make_destination(offsite_bucket)
    enqueue_offsite_uploads()
    push_due_uploads()
    output = tmp_path / "download.tar.age"
    index = tmp_path / "download.tar.age.index.json"
    index.write_bytes(b"preserve this index")
    with pytest.raises(CommandError, match="local_write_failed"):
        call_command("fetch_offsite_archive", "--destination", destination.name,
                     "--archive-id", str(archive.pk), "--output", str(output), stdout=StringIO())
    assert index.read_bytes() == b"preserve this index"
    assert not output.exists()
