"""Object-storage collector protocol for immutable audit attestation anchors."""

import hashlib
import json
from datetime import timedelta

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.utils import timezone

from .anchors_base import (
    AnchorConflict,
    AnchorError,
    _identity,
    _validate_fetched,
    anchors_match,
)
from .anchors_object_rotation import ObjectStorageRotationMixin


class ObjectStorageAnchorSink(ObjectStorageRotationMixin):
    """Immutable one-object-per-sequence sink for an object-lock enabled bucket."""

    def __init__(self):
        self.bucket = str(getattr(settings, "AUDIT_ATTESTATION_S3_BUCKET", ""))
        self.prefix = str(
            getattr(settings, "AUDIT_ATTESTATION_S3_PREFIX", "audit-anchors")
        ).strip("/")
        self.retention_days = int(
            getattr(settings, "AUDIT_ATTESTATION_RETENTION_DAYS", 0)
        )
        # `or "COMPLIANCE"` because BLANK is not the same as absent here. Compose passes
        # `AUDIT_ATTESTATION_S3_OBJECT_LOCK_MODE: ${...:-}`, which makes the variable
        # present-but-empty, and django-environ only applies its default when a variable
        # is ABSENT -- so the setting arrives as "" and the getattr default never fires.
        # Every deployment that left the mode unset in .env therefore refused to anchor.
        # COMPLIANCE is the stricter of the two modes, so defaulting to it fails safe.
        self.lock_mode = str(
            getattr(settings, "AUDIT_ATTESTATION_S3_OBJECT_LOCK_MODE", "") or "COMPLIANCE"
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
        protocol = envelope["payload"].get("anchor_protocol_version", 1)
        scope_latest, scope_signer, _scope_root = self._scope_head(
            identity[0], identity[1]
        )
        if protocol == 2:
            if identity[3] != scope_latest + 1:
                raise AnchorConflict(
                    "The anchor sequence does not continue the scope-global head."
                )
            if scope_signer is not None and scope_signer != identity[2]:
                transition = self.fetch_rotation(
                    (
                        identity[0], identity[1], scope_signer, identity[2],
                        scope_latest,
                    )
                )
                if transition is None:
                    raise AnchorConflict(
                        "The new signer has no anchored cross-key transition."
                    )
            latest_for_signer = self._latest_sequence(identity)
        else:
            if scope_signer is not None and scope_signer != identity[2]:
                raise AnchorConflict(
                    "The signer is not the scope-global anchor authority."
                )
            latest_for_signer = self._latest_sequence(identity)
        if identity[3] == 0 and self._scope_has_another_signer(identity):
            raise AnchorConflict(
                "This deployment scope is already pinned to another signer."
            )
        if identity[3] <= latest_for_signer:
            raise AnchorConflict("The anchor sequence regresses the external head.")
        if protocol != 2 and identity[3] != latest_for_signer + 1:
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
