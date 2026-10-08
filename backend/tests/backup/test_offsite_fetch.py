"""Fresh-host restore-from-offsite: `fetch_offsite_archive` produces a verified local file."""

import hashlib
import json
import os

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command

from apps.backup.models import BackupDestinationUpload
from apps.backup.offsite_push import enqueue_offsite_uploads, push_due_uploads
from tests.backup.offsite_test_support import (
    make_destination,
    offsite_bucket,  # noqa: F401  (fixture)
    stored_archive,
)

pytestmark = pytest.mark.django_db


def _pushed(bucket):
    archive = stored_archive()
    destination = make_destination(bucket)
    enqueue_offsite_uploads()
    push_due_uploads()
    assert BackupDestinationUpload.objects.get(archive_id_snapshot=archive.pk).state == "bytes_verified"
    return archive, destination


def _credentials(tmp_path, destination, mode=0o600):
    path = tmp_path / "offsite.json"
    path.write_text(json.dumps({
        "endpoint_url": destination.endpoint_url,
        "bucket": destination.bucket,
        "region": destination.region,
        "prefix": destination.prefix,
        "addressing_style": destination.addressing_style,
        "access_key_id": settings.AWS_ACCESS_KEY_ID,
        "secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
    }))
    path.chmod(mode)
    return path


def test_fetch_with_a_credentials_file_writes_the_verified_archive(tmp_path, offsite_bucket):
    archive, destination = _pushed(offsite_bucket)
    output = tmp_path / "restore.tar.age"

    call_command(
        "fetch_offsite_archive", "--credentials-file", str(_credentials(tmp_path, destination)),
        "--archive-id", str(archive.pk), "--output", str(output),
    )

    assert hashlib.sha256(output.read_bytes()).hexdigest() == archive.archive_sha256
    assert oct(os.stat(output).st_mode & 0o777) == "0o600"


def test_fetch_from_a_configured_destination_uses_the_journal_digest(tmp_path, offsite_bucket):
    archive, destination = _pushed(offsite_bucket)
    output = tmp_path / "journal.tar.age"
    call_command(
        "fetch_offsite_archive", "--destination", destination.name,
        "--archive-id", str(archive.pk), "--output", str(output),
    )
    assert hashlib.sha256(output.read_bytes()).hexdigest() == archive.archive_sha256


def test_fetch_refuses_a_wrong_expected_digest_and_leaves_no_file(tmp_path, offsite_bucket):
    archive, destination = _pushed(offsite_bucket)
    output = tmp_path / "wrong.tar.age"
    with pytest.raises(CommandError):
        call_command(
            "fetch_offsite_archive", "--credentials-file", str(_credentials(tmp_path, destination)),
            "--archive-id", str(archive.pk), "--output", str(output),
            "--expected-sha256", "0" * 64,
        )
    assert not output.exists()


def test_fetch_refuses_a_group_readable_credentials_file(tmp_path, offsite_bucket):
    archive, destination = _pushed(offsite_bucket)
    with pytest.raises(CommandError, match="0600"):
        call_command(
            "fetch_offsite_archive",
            "--credentials-file", str(_credentials(tmp_path, destination, mode=0o644)),
            "--archive-id", str(archive.pk), "--output", str(tmp_path / "x"),
        )
