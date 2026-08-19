"""Pluggable off-database sinks for immutable audit attestation anchors."""

import hashlib
import json
from datetime import timedelta
from urllib.parse import urlsplit

import boto3
import requests
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime


class AnchorError(RuntimeError):
    pass


class AnchorConflict(AnchorError):
    pass


def _identity(payload):
    return (
        payload["deployment_id"],
        payload["scope"],
        payload["signer_fingerprint"],
        int(payload["batch_seq"]),
    )


def _stable_envelope(envelope):
    return {key: value for key, value in envelope.items() if key != "anchored_at"}


def anchors_match(left, right):
    return _stable_envelope(left) == _stable_envelope(right)


def _validate_fetched(expected_identity, envelope):
    if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
        raise AnchorConflict("The anchor has an invalid envelope.")
    if _identity(envelope["payload"]) != expected_identity:
        raise AnchorConflict("The anchor identity conflicts with the requested batch.")
    anchored_at = parse_datetime(str(envelope.get("anchored_at", "")))
    if anchored_at is None or anchored_at.tzinfo is None:
        raise AnchorConflict("The anchor carries no valid freshness timestamp.")
    return envelope


class ObjectStorageAnchorSink:
    """Immutable one-object-per-sequence sink for an object-lock enabled bucket."""

    def __init__(self):
        self.bucket = str(getattr(settings, "AUDIT_ATTESTATION_S3_BUCKET", ""))
        self.prefix = str(
            getattr(settings, "AUDIT_ATTESTATION_S3_PREFIX", "audit-anchors")
        ).strip("/")
        self.retention_days = int(
            getattr(settings, "AUDIT_ATTESTATION_RETENTION_DAYS", 0)
        )
        self.lock_mode = str(
            getattr(settings, "AUDIT_ATTESTATION_S3_OBJECT_LOCK_MODE", "COMPLIANCE")
        ).upper()
        if not self.bucket or self.retention_days < 1:
            raise AnchorError(
                "The anchor bucket and a positive retention period are required."
            )
        if self.lock_mode not in {"COMPLIANCE", "GOVERNANCE"}:
            raise AnchorError("The S3 object-lock mode is invalid.")

    def _client(self):
        return boto3.client(
            "s3",
            endpoint_url=getattr(
                settings,
                "AUDIT_ATTESTATION_S3_ENDPOINT_URL",
                settings.AWS_S3_ENDPOINT_URL,
            ),
            aws_access_key_id=getattr(
                settings,
                "AUDIT_ATTESTATION_S3_ACCESS_KEY_ID",
                settings.AWS_ACCESS_KEY_ID,
            ),
            aws_secret_access_key=getattr(
                settings,
                "AUDIT_ATTESTATION_S3_SECRET_ACCESS_KEY",
                settings.AWS_SECRET_ACCESS_KEY,
            ),
            region_name=getattr(
                settings,
                "AUDIT_ATTESTATION_S3_REGION_NAME",
                settings.AWS_S3_REGION_NAME,
            ),
            config=Config(
                signature_version=settings.AWS_S3_SIGNATURE_VERSION,
                s3={"addressing_style": settings.AWS_S3_ADDRESSING_STYLE},
            ),
        )

    def _scope_directory(self, deployment_id, scope):
        deployment = hashlib.sha256(deployment_id.encode("utf-8")).hexdigest()
        safe_scope = scope.replace(":", "-")
        return f"{self.prefix}/{deployment}/{safe_scope}"

    def _directory(self, deployment_id, scope, signer):
        return f"{self._scope_directory(deployment_id, scope)}/{signer}"

    def _key(self, identity):
        deployment_id, scope, signer, batch_seq = identity
        return f"{self._directory(deployment_id, scope, signer)}/{batch_seq:020d}.json"

    def fetch(self, identity):
        try:
            response = self._client().get_object(
                Bucket=self.bucket, Key=self._key(identity)
            )
            raw = response["Body"].read()
            return _validate_fetched(identity, json.loads(raw.decode("utf-8")))
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = exc.response.get("Error", {}).get("Code")
            if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise AnchorError("The object anchor could not be fetched.") from exc
        except (BotoCoreError, OSError, UnicodeError, ValueError) as exc:
            raise AnchorError("The object anchor could not be fetched.") from exc

    def _latest_sequence(self, identity):
        deployment_id, scope, signer, _batch_seq = identity
        prefix = self._directory(deployment_id, scope, signer) + "/"
        try:
            paginator = self._client().get_paginator("list_objects_v2")
            sequences = []
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    name = item["Key"].removeprefix(prefix).removesuffix(".json")
                    if name.isdigit():
                        sequences.append(int(name))
            return max(sequences, default=-1)
        except (BotoCoreError, ClientError) as exc:
            raise AnchorError("The object anchor head could not be read.") from exc

    def _scope_has_another_signer(self, identity):
        deployment_id, scope, signer, _batch_seq = identity
        prefix = self._scope_directory(deployment_id, scope) + "/"
        try:
            paginator = self._client().get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    relative = item["Key"].removeprefix(prefix)
                    anchored_signer, separator, _name = relative.partition("/")
                    if separator and anchored_signer != signer:
                        return True
            return False
        except (BotoCoreError, ClientError) as exc:
            raise AnchorError("The object anchor signer pin could not be read.") from exc

    def publish(self, envelope):
        identity = _identity(envelope["payload"])
        existing = self.fetch(identity)
        if existing is not None:
            if not anchors_match(existing, envelope):
                raise AnchorConflict("This anchor sequence already has other content.")
            return existing
        latest = self._latest_sequence(identity)
        if identity[3] == 0 and self._scope_has_another_signer(identity):
            raise AnchorConflict(
                "This deployment scope is already pinned to another signer."
            )
        if identity[3] <= latest:
            raise AnchorConflict("The anchor sequence regresses the external head.")
        if identity[3] != latest + 1:
            raise AnchorConflict("The anchor sequence leaves a gap in the external chain.")
        stored = {**envelope, "anchored_at": timezone.now().isoformat()}
        try:
            self._client().put_object(
                Bucket=self.bucket,
                Key=self._key(identity),
                Body=json.dumps(stored, sort_keys=True, separators=(",", ":")).encode(),
                ContentType="application/json",
                IfNoneMatch="*",
                ObjectLockMode=self.lock_mode,
                ObjectLockRetainUntilDate=timezone.now()
                + timedelta(days=self.retention_days),
            )
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") in {
                409,
                412,
            }:
                existing = self.fetch(identity)
                if existing is not None and anchors_match(existing, envelope):
                    return existing
                raise AnchorConflict("A concurrent conflicting anchor won.") from exc
            raise AnchorError("The object anchor could not be persisted.") from exc
        except BotoCoreError as exc:
            raise AnchorError("The object anchor could not be persisted.") from exc
        return _validate_fetched(identity, stored)


class HttpCollectorAnchorSink:
    """Client for a collector that pins the first signer and enforces its sequence."""

    def __init__(self):
        self.url = str(getattr(settings, "AUDIT_ATTESTATION_HTTP_URL", "")).strip()
        self.token = str(
            getattr(settings, "AUDIT_ATTESTATION_HTTP_BEARER_TOKEN", "")
        )
        self.timeout = float(getattr(settings, "AUDIT_ATTESTATION_HTTP_TIMEOUT", 10))
        parsed = urlsplit(self.url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.fragment:
            raise AnchorError("The audit collector must be an absolute HTTPS URL.")
        if not self.token:
            raise AnchorError("The audit collector bearer token is required.")

    def _headers(self):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def fetch(self, identity):
        deployment_id, scope, signer, batch_seq = identity
        try:
            response = requests.get(
                self.url,
                params={
                    "deployment_id": deployment_id,
                    "scope": scope,
                    "signer_fingerprint": signer,
                    "batch_seq": batch_seq,
                },
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise AnchorError("The HTTP anchor could not be fetched.") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise AnchorError(f"The HTTP anchor fetch returned {response.status_code}.")
        try:
            return _validate_fetched(identity, response.json())
        except (ValueError, TypeError) as exc:
            raise AnchorError("The HTTP collector returned invalid JSON.") from exc

    def publish(self, envelope):
        try:
            response = requests.post(
                self.url,
                json=envelope,
                headers={**self._headers(), "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise AnchorError("The HTTP anchor could not be persisted.") from exc
        if response.status_code == 409:
            raise AnchorConflict("The collector rejected a regressing or conflicting sequence.")
        if response.status_code not in {200, 201}:
            raise AnchorError(f"The HTTP anchor publish returned {response.status_code}.")
        try:
            stored = response.json()
        except ValueError as exc:
            raise AnchorError("The HTTP collector returned invalid JSON.") from exc
        identity = _identity(envelope["payload"])
        _validate_fetched(identity, stored)
        if not anchors_match(stored, envelope):
            raise AnchorConflict("The collector stored content other than the submission.")
        return stored


def configured_sink():
    backend = str(getattr(settings, "AUDIT_ATTESTATION_ANCHOR_BACKEND", "")).lower()
    try:
        if backend == "object_storage":
            return ObjectStorageAnchorSink()
        if backend == "http":
            return HttpCollectorAnchorSink()
    except (TypeError, ValueError) as exc:
        raise AnchorError("The audit anchor settings are invalid.") from exc
    raise AnchorError("AUDIT_ATTESTATION_ANCHOR_BACKEND is not configured.")
