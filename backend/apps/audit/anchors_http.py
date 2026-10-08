"""HTTP collector protocol for immutable audit attestation anchors.

Every failure is classified HERE, where the cause is still visible: a transport problem
(timeout, connection error, 408/425/429/5xx) may be retried, a permanent refusal or bad
setting (401/403/other 4xx) is configuration, and a body that is not valid anchor evidence
is invalid evidence. Callers cannot recover that distinction from a plain ``AnchorError``.
"""

from urllib.parse import urlsplit

import requests
from django.conf import settings

from .anchors_base import (
    MALFORMED_EVIDENCE_ERRORS,
    AnchorConfigurationError,
    AnchorConflict,
    AnchorInvalidEvidence,
    AnchorTransportError,
    _identity,
    _validate_fetched,
    _validate_fetched_rotation,
    anchors_match,
    rotation_identity,
    validate_rotation_envelope,
)
from .anchors_budget import consume

TRANSIENT_STATUSES = frozenset({408, 425, 429})


def status_error(status, what):
    """The typed error for an unexpected collector status code."""
    if status in TRANSIENT_STATUSES or status >= 500:
        return AnchorTransportError(f"The HTTP {what} returned {status}.")
    return AnchorConfigurationError(f"The HTTP {what} was refused with {status}.")


def _decoded(response, validate):
    try:
        return validate(response.json())
    except AnchorConflict:
        raise
    except MALFORMED_EVIDENCE_ERRORS as exc:
        raise AnchorInvalidEvidence("The HTTP collector returned invalid evidence.") from exc


class HttpCollectorAnchorSink:
    """Client for a collector that pins the first signer and enforces its sequence."""

    def __init__(self, read_budget=None):
        self.read_budget = read_budget
        self.url = str(getattr(settings, "AUDIT_ATTESTATION_HTTP_URL", "")).strip()
        self.token = str(
            getattr(settings, "AUDIT_ATTESTATION_HTTP_BEARER_TOKEN", "")
        )
        try:
            self.timeout = float(getattr(settings, "AUDIT_ATTESTATION_HTTP_TIMEOUT", 10))
        except (TypeError, ValueError) as exc:
            raise AnchorConfigurationError("The audit collector timeout is invalid.") from exc
        parsed = urlsplit(self.url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.fragment:
            raise AnchorConfigurationError("The audit collector must be an absolute HTTPS URL.")
        if not self.token:
            raise AnchorConfigurationError("The audit collector bearer token is required.")

    def _headers(self):
        headers = {
            "Accept": "application/json",
            "X-SpaceWorks-Audit-Anchor-Protocol": "2",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, params, what):
        consume(self.read_budget)
        try:
            return requests.get(
                self.url, params=params, headers=self._headers(), timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise AnchorTransportError(f"The HTTP {what} could not be fetched.") from exc

    def _post(self, envelope, what):
        try:
            return requests.post(
                self.url,
                json=envelope,
                headers={**self._headers(), "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise AnchorTransportError(f"The HTTP {what} could not be persisted.") from exc

    def fetch(self, identity):
        deployment_id, scope, signer, batch_seq = identity
        response = self._get(
            {
                "deployment_id": deployment_id,
                "scope": scope,
                "signer_fingerprint": signer,
                "batch_seq": batch_seq,
            },
            "anchor fetch",
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise status_error(response.status_code, "anchor fetch")
        return _decoded(response, lambda body: _validate_fetched(identity, body))

    def publish(self, envelope):
        response = self._post(envelope, "anchor")
        if response.status_code == 409:
            raise AnchorConflict("The collector rejected a regressing or conflicting sequence.")
        if response.status_code not in {200, 201}:
            raise status_error(response.status_code, "anchor publish")
        identity = _identity(envelope["payload"])
        stored = _decoded(response, lambda body: _validate_fetched(identity, body))
        if not anchors_match(stored, envelope):
            raise AnchorConflict("The collector stored content other than the submission.")
        return stored

    @staticmethod
    def rotation_identity(envelope):
        return rotation_identity(envelope)

    def fetch_rotation(self, identity):
        deployment_id, scope, old_signer, new_signer, batch_seq = identity
        response = self._get(
            {
                "entry_type": "key_rotation",
                "deployment_id": deployment_id,
                "scope": scope,
                "old_fingerprint": old_signer,
                "new_fingerprint": new_signer,
                "last_old_batch_seq": batch_seq,
            },
            "rotation-anchor fetch",
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise status_error(response.status_code, "rotation-anchor fetch")
        return _decoded(
            response, lambda body: _validate_fetched_rotation(identity, body)
        )

    def publish_rotation(self, envelope):
        validate_rotation_envelope(envelope)
        response = self._post(envelope, "rotation anchor")
        if response.status_code == 409:
            raise AnchorConflict("The collector rejected the key transition.")
        if response.status_code not in {200, 201}:
            raise status_error(response.status_code, "rotation-anchor publish")
        identity = rotation_identity(envelope)
        stored = _decoded(
            response, lambda body: _validate_fetched_rotation(identity, body)
        )
        if not anchors_match(stored, envelope):
            raise AnchorConflict("The collector stored a different key transition.")
        return stored

    def fetch_scope_head(self, deployment_id, scope):
        response = self._get(
            {"entry_type": "scope_head", "deployment_id": deployment_id, "scope": scope},
            "scope-head fetch",
        )
        if response.status_code == 404:
            # Unlike a point read, a collector always has a scope head (possibly empty).
            # Its absence is missing evidence, not a reason to retry.
            raise AnchorInvalidEvidence("The HTTP collector has no scope-global head.")
        if response.status_code != 200:
            raise status_error(response.status_code, "scope-head fetch")
        try:
            payload = response.json()
            sequence = int(payload["batch_seq"])
            signer = str(payload["signer_fingerprint"])
            root = bytes.fromhex(payload["merkle_root"])
            if sequence < 0 or len(root) != 32 or len(signer) != 64:
                raise ValueError
        except MALFORMED_EVIDENCE_ERRORS as exc:
            raise AnchorConflict("The HTTP scope-global head is invalid.") from exc
        return sequence, signer, root
