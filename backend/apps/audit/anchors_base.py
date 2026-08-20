"""Shared envelope rules for immutable audit attestation anchors."""

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
