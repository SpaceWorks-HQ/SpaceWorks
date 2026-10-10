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
    AnchorConfigurationError,
    AnchorConflict,
    _identity,
    _validate_fetched,
    anchors_match,
)
from .anchors_object_io import classify_storage_error, iter_object_keys, read_json_object
from .anchors_object_rotation import ObjectStorageRotationMixin


class ObjectStorageAnchorSink(ObjectStorageRotationMixin):
    """Immutable one-object-per-sequence sink for an object-lock enabled bucket."""

    def __init__(self, read_budget=None):
        self.read_budget = read_budget
        self.bucket = str(getattr(settings, "AUDIT_ATTESTATION_S3_BUCKET", ""))
        self.prefix = str(
            getattr(settings, "AUDIT_ATTESTATION_S3_PREFIX", "audit-anchors")
        ).strip("/")
        try:
            self.retention_days = int(
                getattr(settings, "AUDIT_ATTESTATION_RETENTION_DAYS", 0)
            )
        except (TypeError, ValueError) as exc:
            raise AnchorConfigurationError("The anchor retention period is invalid.") from exc
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
            raise AnchorConfigurationError(
                "The anchor bucket and a positive retention period are required."
            )
        if self.lock_mode not in {"COMPLIANCE", "GOVERNANCE"}:
            raise AnchorConfigurationError("The S3 object-lock mode is invalid.")

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

    def _keys(self, prefix, message):
        return iter_object_keys(
            self._client(), self.bucket, prefix, self.read_budget, message
        )

    def fetch(self, identity):
        return read_json_object(
            self._client(), self.bucket, self._key(identity),
            lambda body: _validate_fetched(identity, body), self.read_budget,
        )

    def _latest_sequence(self, identity):
        deployment_id, scope, signer, _batch_seq = identity
        prefix = self._directory(deployment_id, scope, signer) + "/"
        sequences = []
        for key in self._keys(prefix, "The object anchor head could not be read."):
            name = key.removeprefix(prefix).removesuffix(".json")
            if name.isdigit():
                sequences.append(int(name))
        return max(sequences, default=-1)

    def _scope_has_another_signer(self, identity):
        deployment_id, scope, signer, _batch_seq = identity
        prefix = self._scope_directory(deployment_id, scope) + "/"
        for key in self._keys(prefix, "The object anchor signer pin could not be read."):
            anchored_signer, separator, _name = key.removeprefix(prefix).partition("/")
            if separator and anchored_signer != signer:
                return True
        return False

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
            raise classify_storage_error(
                exc, "The object anchor could not be persisted."
            ) from exc
        except BotoCoreError as exc:
            raise classify_storage_error(
                exc, "The object anchor could not be persisted."
            ) from exc
        return _validate_fetched(identity, stored)
