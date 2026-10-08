"""Download one archive from an offsite destination to a local file, verified.

The fresh-host half of restore-from-offsite. The output is an ordinary encrypted
archive file for `scripts/import-backup.sh`, whose import preflight then checks the
host-trusted Ed25519 signature, format and compatibility exactly as for any other
archive. The SHA-256 checked here proves the bytes are the ones that were pushed; a
sidecar index on the same destination is same-trust-domain, so pass
`--expected-sha256` from an independent record whenever you have one.

Credentials come from a configured destination (`--destination`) or from a JSON file
(`--credentials-file`, mode 0600, regular file, not a symlink). They are never
accepted on the command line or through the environment.
"""

import json
import os
import re
import stat
import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.backup import offsite_client

CREDENTIAL_FIELDS = (
    "endpoint_url", "bucket", "region", "prefix", "addressing_style",
    "access_key_id", "secret_access_key",
)


class _FileDestination:
    def __init__(self, values):
        self.endpoint_url = values.get("endpoint_url", "")
        self.bucket = values["bucket"]
        self.region = values.get("region", "")
        self.prefix = values.get("prefix", "")
        self.addressing_style = values.get("addressing_style", "auto")
        self._access = values["access_key_id"]
        self._secret = values["secret_access_key"]

    def get_access_key_id(self):
        return self._access

    def get_secret_access_key(self):
        return self._secret


def load_credentials_file(path):
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise CommandError("The credentials file cannot be read.") from exc
    if not stat.S_ISREG(info.st_mode):
        raise CommandError("The credentials file must be a regular file, not a link.")
    if os.name == "posix" and info.st_mode & 0o077:
        raise CommandError("The credentials file must be mode 0600 (no group/other access).")
    try:
        with open(path, encoding="utf-8") as handle:
            values = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CommandError("The credentials file is not valid JSON.") from exc
    if not isinstance(values, dict) or set(values) - set(CREDENTIAL_FIELDS):
        raise CommandError(f"The credentials file may contain only: {', '.join(CREDENTIAL_FIELDS)}.")
    for required in ("bucket", "access_key_id", "secret_access_key"):
        if not values.get(required):
            raise CommandError(f"The credentials file needs {required}.")
    return _FileDestination(values)


class Command(BaseCommand):
    help = "Fetch and verify one archive from an offsite destination for import-backup.sh."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--destination", help="Name of a configured destination.")
        source.add_argument("--credentials-file", help="Mode-0600 JSON credentials file.")
        parser.add_argument("--archive-id", help="Archive UUID to fetch.")
        parser.add_argument("--scope", default="deployment", choices=("deployment", "makerspace"))
        parser.add_argument("--output", help="Local path to write; must not exist.")
        parser.add_argument("--expected-sha256")
        parser.add_argument("--list", action="store_true", help="List archives on the destination.")

    def handle(self, *args, **options):
        destination, journal = self._destination(options)
        try:
            s3 = offsite_client.destination_client(destination)
        except offsite_client.OffsiteDestinationError as exc:
            raise CommandError(f"Destination unusable [{exc.code}].") from exc
        if options["list"]:
            return self._list(s3, destination)
        try:
            archive_id = uuid.UUID(str(options["archive_id"]))
        except ValueError as exc:
            raise CommandError("--archive-id must be a UUID.") from exc
        if not options["output"]:
            raise CommandError("--output is required.")
        locator = offsite_client.remote_locator(destination, archive_id, options["scope"])
        expected_size, expected_sha256 = self._expected(
            s3, destination, locator, archive_id, journal, options["expected_sha256"]
        )
        self._download(s3, destination, locator, options["output"], expected_size, expected_sha256)
        self.stdout.write(f"{expected_sha256}  {options['output']}")
        self.stdout.write(
            "Verified. Next: scripts/import-backup.sh with --expected-sha256 "
            f"{expected_sha256}; its preflight checks the archive signature."
        )

    def _destination(self, options):
        if options["credentials_file"]:
            return load_credentials_file(options["credentials_file"]), None
        from apps.backup.models import BackupDestination, BackupDestinationUpload

        destination = BackupDestination.objects.filter(
            name=options["destination"], retired_at__isnull=True
        ).first()
        if destination is None:
            raise CommandError("No active destination has that name.")
        return destination, BackupDestinationUpload.objects.filter(destination=destination)

    def _expected(self, s3, destination, locator, archive_id, journal, supplied):
        if supplied is not None and not re.fullmatch(r"[0-9a-f]{64}", supplied):
            raise CommandError("--expected-sha256 must be 64 lowercase hex characters.")
        row = journal.filter(archive_id_snapshot=archive_id).first() if journal is not None else None
        if row is not None:
            if supplied and supplied != row.expected_sha256:
                raise CommandError("--expected-sha256 disagrees with this deployment's journal.")
            return row.expected_size_bytes, row.expected_sha256
        try:
            index = offsite_client.read_index(s3, destination.bucket, locator)
        except offsite_client.OffsiteDestinationError as exc:
            if supplied is None:
                raise CommandError(f"No index sidecar and no --expected-sha256 [{exc.code}].") from exc
            index = {}
        if supplied and index.get("sha256") not in (None, supplied):
            raise CommandError("--expected-sha256 disagrees with the destination's index sidecar.")
        if str(index.get("archive_id", archive_id)) != str(archive_id):
            raise CommandError("The index sidecar names a different archive.")
        sha256 = supplied or index.get("sha256")
        size = index.get("size_bytes")
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise CommandError("No trustworthy sha256 is available for this archive.")
        if size is None:
            raise CommandError("The archive size is unknown; the index sidecar is missing it.")
        return int(size), sha256

    def _download(self, s3, destination, locator, output, expected_size, expected_sha256):
        try:
            fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            raise CommandError("The output path must not already exist.") from exc
        try:
            with os.fdopen(fd, "wb") as sink:
                offsite_client.read_back(
                    s3, destination.bucket, locator,
                    expected_size=expected_size, expected_sha256=expected_sha256, sink=sink,
                )
        except offsite_client.OffsiteDestinationError as exc:
            os.unlink(output)
            raise CommandError(f"Fetch refused [{exc.code}]; the partial file was removed.") from exc

    def _list(self, s3, destination):
        prefix = offsite_client.remote_locator(destination, "x", "x").rsplit("/", 2)[0] + "/"
        token = None
        while True:
            params = {"Bucket": destination.bucket, "Prefix": prefix}
            if token:
                params["ContinuationToken"] = token
            try:
                page = s3.list_objects_v2(**params)
            except Exception as exc:
                raise CommandError("The destination could not be listed.") from exc
            for item in page.get("Contents", []):
                if item["Key"].endswith(".tar.age"):
                    self.stdout.write(f"{item['LastModified'].isoformat()}  {item['Size']}  {item['Key']}")
            if not page.get("IsTruncated"):
                return
            token = page.get("NextContinuationToken")
