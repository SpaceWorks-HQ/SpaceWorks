"""Scope-global cross-key protocol layered onto object-storage anchors."""

import hmac
import json
from datetime import timedelta

from botocore.exceptions import BotoCoreError, ClientError
from django.utils import timezone

from .anchors_base import (
    AnchorConflict,
    AnchorError,
    _validate_fetched_rotation,
    anchors_match,
    rotation_identity,
    validate_rotation_envelope,
)


class ObjectStorageRotationMixin:
    def _rotation_key(self, identity):
        deployment_id, scope, old_signer, new_signer, batch_seq = identity
        directory = self._scope_directory(deployment_id, scope)
        return (
            f"{directory}/transitions/{batch_seq:020d}-"
            f"{old_signer}-{new_signer}.json"
        )

    def _scope_batch_head(self, deployment_id, scope):
        prefix = self._scope_directory(deployment_id, scope) + "/"
        candidates = []
        try:
            paginator = self._client().get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    relative = item["Key"].removeprefix(prefix)
                    signer, separator, name = relative.partition("/")
                    sequence = name.removesuffix(".json")
                    if separator and signer != "transitions" and sequence.isdigit():
                        candidates.append((int(sequence), signer))
        except (BotoCoreError, ClientError) as exc:
            raise AnchorError("The scope-global anchor head could not be read.") from exc
        if not candidates:
            return -1, None, None
        sequence, signer = max(candidates)
        envelope = self.fetch((deployment_id, scope, signer, sequence))
        root = envelope["payload"].get("merkle_root")
        return sequence, signer, bytes.fromhex(root) if root is not None else bytes(32)

    def _scope_head(self, deployment_id, scope):
        sequence, signer, root = self._scope_batch_head(deployment_id, scope)
        if signer is None:
            return sequence, signer, root
        prefix = self._scope_directory(deployment_id, scope) + "/transitions/"
        try:
            paginator = self._client().get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    name = item["Key"].removeprefix(prefix).removesuffix(".json")
                    seq_text, separator, fingerprints = name.partition("-")
                    if not separator or not seq_text.isdigit() or int(seq_text) != sequence:
                        continue
                    old_signer, separator, new_signer = fingerprints.partition("-")
                    if separator and old_signer == signer:
                        identity = (deployment_id, scope, old_signer, new_signer, sequence)
                        if self.fetch_rotation(identity) is not None:
                            signer = new_signer
        except (BotoCoreError, ClientError) as exc:
            raise AnchorError("The scope-global transition head could not be read.") from exc
        return sequence, signer, root

    def fetch_scope_head(self, deployment_id, scope):
        return self._scope_head(deployment_id, scope)

    @staticmethod
    def rotation_identity(envelope):
        return rotation_identity(envelope)

    def fetch_rotation(self, identity):
        try:
            response = self._client().get_object(
                Bucket=self.bucket, Key=self._rotation_key(identity)
            )
            raw = response["Body"].read()
            return _validate_fetched_rotation(
                identity, json.loads(raw.decode("utf-8"))
            )
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = exc.response.get("Error", {}).get("Code")
            if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise AnchorError("The object rotation anchor could not be fetched.") from exc
        except (BotoCoreError, OSError, UnicodeError, ValueError) as exc:
            raise AnchorError("The object rotation anchor could not be fetched.") from exc

    def publish_rotation(self, envelope):
        validate_rotation_envelope(envelope)
        identity = rotation_identity(envelope)
        existing = self.fetch_rotation(identity)
        if existing is not None:
            if not anchors_match(existing, envelope):
                raise AnchorConflict("This key transition already has other content.")
            return existing
        head_seq, head_signer, head_root = self._scope_batch_head(identity[0], identity[1])
        expected_root = bytes.fromhex(envelope["payload"]["last_old_batch_root"])
        if (
            head_seq != identity[4]
            or head_signer != identity[2]
            or not hmac.compare_digest(head_root, expected_root)
        ):
            raise AnchorConflict("The key transition does not bind the scope-global head.")
        stored = {**envelope, "anchored_at": timezone.now().isoformat()}
        try:
            self._client().put_object(
                Bucket=self.bucket, Key=self._rotation_key(identity),
                Body=json.dumps(stored, sort_keys=True, separators=(",", ":")).encode(),
                ContentType="application/json", IfNoneMatch="*",
                ObjectLockMode=self.lock_mode,
                ObjectLockRetainUntilDate=timezone.now()
                + timedelta(days=self.retention_days),
            )
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") in {409, 412}:
                existing = self.fetch_rotation(identity)
                if existing is not None and anchors_match(existing, envelope):
                    return existing
                raise AnchorConflict("A concurrent conflicting transition won.") from exc
            raise AnchorError("The object rotation anchor could not be persisted.") from exc
        except BotoCoreError as exc:
            raise AnchorError("The object rotation anchor could not be persisted.") from exc
        return _validate_fetched_rotation(identity, stored)
