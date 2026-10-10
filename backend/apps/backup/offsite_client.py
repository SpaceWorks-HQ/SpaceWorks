"""S3-compatible client and byte primitives for one offsite destination.

Every failure surfaces as `OffsiteDestinationError` carrying a short, stable code and
no credential, endpoint secret or provider message: those strings end up in the
journal, the API and logs, and a provider error can echo a signed request back.
"""

import hashlib
import hmac
import json

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from cryptography.fernet import InvalidToken
from django.core.exceptions import ImproperlyConfigured

from apps.object_storage import delete_all_versions


CHUNK_SIZE = 1024 * 1024
CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 120


class OffsiteDestinationError(RuntimeError):
    def __init__(self, code, message="The offsite destination operation failed."):
        super().__init__(message)
        self.code = code


def destination_client(destination):
    try:
        access_key = destination.get_access_key_id()
        secret_key = destination.get_secret_access_key()
    except (InvalidToken, ValueError, ImproperlyConfigured) as exc:
        raise OffsiteDestinationError("credentials_unreadable") from exc
    if not access_key or not secret_key:
        raise OffsiteDestinationError(
            "credentials_missing", "The destination has no stored credentials."
        )
    try:
        return client_for(
            endpoint_url=destination.endpoint_url,
            region=destination.region,
            addressing_style=destination.addressing_style,
            access_key_id=access_key,
            secret_access_key=secret_key,
        )
    except (BotoCoreError, ValueError) as exc:
        raise OffsiteDestinationError("client_unavailable") from exc


def client_for(
    *, endpoint_url, region, addressing_style, access_key_id, secret_access_key,
    signature_version="s3v4",
):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or None,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region or None,
        config=Config(
            signature_version=signature_version,
            s3={"addressing_style": addressing_style or "auto"},
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            read_timeout=READ_TIMEOUT_SECONDS,
            retries={"max_attempts": 2, "mode": "standard"},
            # Streamed bodies are not seekable; flexible checksums would seek them, and
            # several S3-compatible providers reject the newer checksum headers anyway.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def remote_locator(destination, archive_id, scope):
    prefix = destination.prefix.strip("/")
    name = f"spaceworks-backups/{scope}/{archive_id}.tar.age"
    return f"{prefix}/{name}" if prefix else name


def index_locator(locator):
    return f"{locator}.index.json"


class HashingReader:
    """File-like wrapper that hashes and counts what the uploader pulls through it."""

    def __init__(self, body):
        self._body = body
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, amount=-1):
        chunk = self._body.read(CHUNK_SIZE if amount is None or amount < 0 else amount)
        if chunk:
            self.digest.update(chunk)
            self.size += len(chunk)
        return chunk


def stream_copy(source_body, s3, bucket, locator):
    """Upload `source_body` to the destination; return what was actually sent."""
    reader = HashingReader(source_body)
    try:
        s3.upload_fileobj(
            reader, bucket, locator, ExtraArgs={"ContentType": "application/octet-stream"}
        )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise OffsiteDestinationError(_code(exc, "upload_failed")) from exc
    return reader.size, reader.digest.hexdigest()


def put_index(s3, bucket, locator, facts):
    body = json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()
    try:
        s3.put_object(
            Bucket=bucket, Key=index_locator(locator), Body=body,
            ContentType="application/json",
        )
    except (BotoCoreError, ClientError) as exc:
        raise OffsiteDestinationError(_code(exc, "index_upload_failed")) from exc


def read_back(s3, bucket, locator, *, expected_size, expected_sha256, sink=None):
    """Stream the remote object; verify size and SHA-256. HEAD/ETag prove nothing."""
    body = None
    digest = hashlib.sha256()
    size = 0
    try:
        body = s3.get_object(Bucket=bucket, Key=locator)["Body"]
        while chunk := body.read(CHUNK_SIZE):
            size += len(chunk)
            digest.update(chunk)
            if sink is not None:
                sink.write(chunk)
    except (BotoCoreError, ClientError, OSError) as exc:
        raise OffsiteDestinationError(_code(exc, "read_back_failed")) from exc
    finally:
        if body is not None and hasattr(body, "close"):
            body.close()
    actual = digest.hexdigest()
    if size != expected_size or not hmac.compare_digest(actual, expected_sha256):
        raise OffsiteDestinationError(
            "digest_mismatch",
            "The offsite copy does not match its recorded size and sha256.",
        )
    return size, actual


def open_remote(s3, bucket, locator):
    try:
        return s3.get_object(Bucket=bucket, Key=locator)["Body"]
    except (BotoCoreError, ClientError) as exc:
        raise OffsiteDestinationError(_code(exc, "read_failed")) from exc


def read_index(s3, bucket, locator):
    body = open_remote(s3, bucket, index_locator(locator))
    try:
        value = json.loads(body.read(64 * 1024).decode())
        if not isinstance(value, dict):
            raise OffsiteDestinationError("index_invalid")
        return value
    except (ValueError, UnicodeDecodeError) as exc:
        raise OffsiteDestinationError("index_invalid") from exc
    except (BotoCoreError, ClientError, OSError) as exc:
        raise OffsiteDestinationError("index_read_failed") from exc
    finally:
        body.close()


def delete_remote(s3, bucket, locator):
    try:
        delete_all_versions(s3, bucket=bucket, key=locator)
        delete_all_versions(s3, bucket=bucket, key=index_locator(locator))
    except (BotoCoreError, ClientError) as exc:
        raise OffsiteDestinationError(_code(exc, "delete_failed")) from exc


def probe(destination, *, nonce):
    """Round-trip a tiny object to prove credentials, bucket and delete permission."""
    s3 = destination_client(destination)
    locator = remote_locator(destination, f"probe-{nonce}", "probe")
    payload = f"spaceworks-offsite-probe:{nonce}".encode()
    try:
        s3.put_object(Bucket=destination.bucket, Key=locator, Body=payload)
    except (BotoCoreError, ClientError) as exc:
        raise OffsiteDestinationError(_code(exc, "probe_write_failed")) from exc
    read_back(
        s3, destination.bucket, locator,
        expected_size=len(payload), expected_sha256=hashlib.sha256(payload).hexdigest(),
    )
    try:
        delete_all_versions(s3, bucket=destination.bucket, key=locator)
    except (BotoCoreError, ClientError) as exc:
        raise OffsiteDestinationError(_code(exc, "probe_delete_failed")) from exc


def _code(exc, fallback):
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", "")).strip()
        if code and code.replace("_", "").isalnum() and len(code) <= 40:
            return f"s3_{code}"[:64]
    return fallback
