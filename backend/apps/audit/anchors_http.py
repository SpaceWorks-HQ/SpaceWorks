"""HTTP collector protocol for immutable audit attestation anchors."""

from urllib.parse import urlsplit

import requests
from django.conf import settings

from .anchors_base import (
    AnchorConflict,
    AnchorError,
    _identity,
    _validate_fetched,
    _validate_fetched_rotation,
    anchors_match,
    rotation_identity,
    validate_rotation_envelope,
)


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
        headers = {
            "Accept": "application/json",
            "X-SpaceWorks-Audit-Anchor-Protocol": "2",
        }
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

    @staticmethod
    def rotation_identity(envelope):
        return rotation_identity(envelope)

    def fetch_rotation(self, identity):
        deployment_id, scope, old_signer, new_signer, batch_seq = identity
        try:
            response = requests.get(
                self.url,
                params={
                    "entry_type": "key_rotation",
                    "deployment_id": deployment_id,
                    "scope": scope,
                    "old_fingerprint": old_signer,
                    "new_fingerprint": new_signer,
                    "last_old_batch_seq": batch_seq,
                },
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise AnchorError("The HTTP rotation anchor could not be fetched.") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise AnchorError(
                f"The HTTP rotation-anchor fetch returned {response.status_code}."
            )
        try:
            return _validate_fetched_rotation(identity, response.json())
        except (ValueError, TypeError) as exc:
            raise AnchorError("The HTTP collector returned invalid JSON.") from exc

    def publish_rotation(self, envelope):
        validate_rotation_envelope(envelope)
        try:
            response = requests.post(
                self.url,
                json=envelope,
                headers={**self._headers(), "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise AnchorError("The HTTP rotation anchor could not be persisted.") from exc
        if response.status_code == 409:
            raise AnchorConflict("The collector rejected the key transition.")
        if response.status_code not in {200, 201}:
            raise AnchorError(
                f"The HTTP rotation-anchor publish returned {response.status_code}."
            )
        try:
            stored = response.json()
        except ValueError as exc:
            raise AnchorError("The HTTP collector returned invalid JSON.") from exc
        identity = rotation_identity(envelope)
        _validate_fetched_rotation(identity, stored)
        if not anchors_match(stored, envelope):
            raise AnchorConflict("The collector stored a different key transition.")
        return stored

    def fetch_scope_head(self, deployment_id, scope):
        try:
            response = requests.get(
                self.url,
                params={
                    "entry_type": "scope_head",
                    "deployment_id": deployment_id,
                    "scope": scope,
                },
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise AnchorError("The HTTP scope-global head could not be fetched.") from exc
        if response.status_code != 200:
            raise AnchorError(
                f"The HTTP scope-head fetch returned {response.status_code}."
            )
        try:
            payload = response.json()
            sequence = int(payload["batch_seq"])
            signer = str(payload["signer_fingerprint"])
            root = bytes.fromhex(payload["merkle_root"])
            if sequence < 0 or len(root) != 32 or len(signer) != 64:
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise AnchorConflict("The HTTP scope-global head is invalid.") from exc
        return sequence, signer, root
