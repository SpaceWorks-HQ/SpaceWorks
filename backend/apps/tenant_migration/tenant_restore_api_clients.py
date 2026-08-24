"""Artifact-bound, idempotent Lane D API-client reissuance."""

from __future__ import annotations

from datetime import datetime, timezone as datetime_timezone
import hashlib
import json
import re
import secrets
import uuid

from django.db import transaction
from django.utils import timezone

from apps.apiclients.models import ApiClient, ApiClientImportApproval
from apps.apiclients.origin_validation import validate_exact_origins
from apps.apiclients.scope_grants import validate_grantable_scopes
from apps.apiclients.services import sync_makerspace_origins
from apps.audit import services as audit
from apps.makerspaces import limits

from .tenant_restore_types import TenantRestoreRefused


SHA256 = re.compile(r"^[0-9a-f]{64}$")
APPROVAL_FIELDS = {
    "artifact_sha256", "capture_id", "source_catalog_sha256",
    "source_client_ref", "source_entry_sha256", "label", "client_type",
    "rate_limit_tier", "target_scopes", "target_origins",
    "privileged_scopes_approved", "host_principal", "approved_at",
    "expires_at", "nonce", "approval_record_sha256",
}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value):
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def provenance_digest(*, artifact_sha256, makerspace_id, source_client_ref):
    payload = (
        "lane-d-apiclient-v1\0" + artifact_sha256 + "\0"
        + str(makerspace_id) + "\0" + source_client_ref
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_approvals(document, *, artifact_sha256, capture_id, catalog, now=None):
    now = now or datetime.now(datetime_timezone.utc)
    if now.tzinfo is None:
        raise TenantRestoreRefused("API-client approval clock must be timezone-aware.")
    try:
        capture_id = str(uuid.UUID(str(capture_id)))
    except (ValueError, TypeError) as exc:
        raise TenantRestoreRefused("API-client approval capture ID is invalid.") from exc
    if not _is_sha256(artifact_sha256):
        raise TenantRestoreRefused("API-client approval artifact digest is invalid.")
    if (
        not isinstance(catalog, dict)
        or not {"entries", "sha256"}.issubset(catalog)
        or not isinstance(catalog["entries"], list)
        or not _is_sha256(catalog["sha256"])
    ):
        raise TenantRestoreRefused("The source API-client catalog is malformed.")
    ordered = catalog["entries"]
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("source_client_ref"), str)
        or not _is_sha256(item["source_client_ref"])
        for item in ordered
    ) or ordered != sorted(
        ordered, key=lambda item: item.get("source_client_ref", "")
    ):
        raise TenantRestoreRefused("The source API-client catalog is not canonical.")
    entries = {item.get("source_client_ref"): item for item in ordered}
    if None in entries or len(entries) != len(ordered):
        raise TenantRestoreRefused("The source API-client catalog contains duplicate references.")
    for source in ordered:
        source_digest = source.get("source_entry_sha256")
        unsigned = {key: value for key, value in source.items() if key != "source_entry_sha256"}
        if not _is_sha256(source_digest) or _digest(unsigned) != source_digest:
            raise TenantRestoreRefused("A source API-client catalog entry digest changed.")
    if _digest(ordered) != catalog["sha256"]:
        raise TenantRestoreRefused("The source API-client catalog digest changed.")
    allowed_document_shapes = ({"approvals"}, {"version", "approvals"})
    records = document.get("approvals") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or set(document) not in allowed_document_shapes
        or ("version" in document and document["version"] != 1)
    ):
        records = None
    if not isinstance(records, list):
        raise TenantRestoreRefused("The API-client approval file is malformed.")
    approved = []
    seen_refs = set()
    seen_nonces = set()
    for raw in records:
        if not isinstance(raw, dict) or set(raw) != APPROVAL_FIELDS:
            raise TenantRestoreRefused("An API-client approval record is malformed.")
        record = dict(raw)
        record_sha256 = record.pop("approval_record_sha256")
        if not _is_sha256(record_sha256) or _digest(record) != record_sha256:
            raise TenantRestoreRefused("An API-client approval record digest changed.")
        ref = record.get("source_client_ref")
        nonce = record.get("nonce")
        if (
            not _is_sha256(ref)
            or not isinstance(nonce, str)
            or not 0 < len(nonce) <= 64
            or "\x00" in nonce
        ):
            raise TenantRestoreRefused("API-client approval reference or nonce is invalid.")
        if type(record.get("privileged_scopes_approved")) is not bool:
            raise TenantRestoreRefused("API-client privileged approval flag is invalid.")
        if ref in seen_refs or nonce in seen_nonces:
            raise TenantRestoreRefused("API-client approval references or nonces are duplicated.")
        seen_refs.add(ref)
        seen_nonces.add(nonce)
        source = entries.get(ref)
        if not source or source.get("eligible_for_reissue") is not True:
            raise TenantRestoreRefused("An API-client approval names an ineligible source client.")
        required_equal = {
            "artifact_sha256": artifact_sha256,
            "capture_id": capture_id,
            "source_catalog_sha256": catalog["sha256"],
            "source_entry_sha256": source["source_entry_sha256"],
            "label": source["label"],
            "client_type": source["client_type"],
            "rate_limit_tier": source["rate_limit_tier"],
        }
        if any(record.get(key) != value for key, value in required_equal.items()):
            raise TenantRestoreRefused("An API-client approval conflicts with its source entry.")
        try:
            expires = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
            approved_at = datetime.fromisoformat(
                record["approved_at"].replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TenantRestoreRefused("API-client approval timestamps are invalid.") from exc
        if (
            expires.tzinfo is None
            or approved_at.tzinfo is None
            or expires <= now
            or approved_at > now
            or approved_at >= expires
            or not isinstance(record.get("host_principal"), str)
            or not record["host_principal"].strip()
            or len(record["host_principal"]) > 255
            or "\x00" in record["host_principal"]
        ):
            raise TenantRestoreRefused("API-client approval is expired or unattributed.")
        try:
            scopes = validate_grantable_scopes(
                record.get("target_scopes"),
                privileged=record.get("privileged_scopes_approved") is True,
            )
            origins = validate_exact_origins(record.get("target_origins"))
        except ValueError as exc:
            raise TenantRestoreRefused(
                "API-client approval scopes or origins are invalid."
            ) from exc
        if (
            not isinstance(source.get("canonical_scopes"), list)
            or not set(scopes).issubset(source["canonical_scopes"])
        ):
            raise TenantRestoreRefused("API-client approval widens source scopes.")
        record["target_scopes"] = scopes
        record["target_origins"] = origins
        record["approval_record_sha256"] = record_sha256
        approved.append(record)
    return tuple(approved)


def reissue_approved_client(*, makerspace, record, delivery_store):
    provenance = provenance_digest(
        artifact_sha256=record["artifact_sha256"],
        makerspace_id=makerspace.pk,
        source_client_ref=record["source_client_ref"],
    )
    existing = ApiClient.objects.filter(import_provenance_digest=provenance).first()
    if existing is not None:
        _assert_existing(existing, makerspace, record)
        if existing.credential_delivered_at is None:
            delivery_store.prepare(
                provenance=provenance,
                kind="api_client",
                target=record["source_client_ref"],
                secret=existing.get_secret(),
            )
        return existing
    delivery = delivery_store.get_or_prepare(
        provenance=provenance,
        kind="api_client",
        target=record["source_client_ref"],
        secret_factory=lambda: secrets.token_urlsafe(32),
    )
    raw_secret = delivery["secret"]
    with transaction.atomic():
        limits.check_quota(makerspace, "api_clients", adding=1)
        client, _ = ApiClient.issue(
            label=record["label"],
            scopes=record["target_scopes"],
            makerspace=makerspace,
            allowed_origins=record["target_origins"],
            client_type=record["client_type"],
            rate_limit_tier=record["rate_limit_tier"],
            raw_secret=raw_secret,
            import_provenance_digest=provenance,
        )
        ApiClientImportApproval.objects.create(
            makerspace=makerspace,
            api_client=client,
            artifact_sha256=record["artifact_sha256"],
            capture_id=record["capture_id"],
            source_catalog_sha256=record["source_catalog_sha256"],
            source_client_ref=record["source_client_ref"],
            source_entry_sha256=record["source_entry_sha256"],
            approval_record_sha256=record["approval_record_sha256"],
            host_principal=record["host_principal"],
            approval_nonce=record["nonce"],
            approved_at=record["approved_at"],
            expires_at=record["expires_at"],
        )
        audit.record(
            None,
            "tenant_migration.api_client_reissued",
            makerspace=makerspace,
            target=client,
            meta={"source_client_ref": record["source_client_ref"], "provenance": provenance},
        )
        transaction.on_commit(lambda: sync_makerspace_origins(makerspace), robust=True)
    return client


def _assert_existing(client, makerspace, record):
    expected = (
        makerspace.pk, record["label"], record["client_type"], record["rate_limit_tier"],
        record["target_scopes"], record["target_origins"],
    )
    actual = (
        client.makerspace_id, client.label, client.client_type, client.rate_limit_tier,
        client.scopes, client.allowed_origins,
    )
    if actual != expected:
        raise TenantRestoreRefused("Existing API-client import provenance conflicts.")
    approval = ApiClientImportApproval.objects.filter(api_client=client).first()
    if approval is None or (
        approval.artifact_sha256,
        str(approval.capture_id),
        approval.source_catalog_sha256,
        approval.source_client_ref,
        approval.source_entry_sha256,
        approval.approval_record_sha256,
        approval.host_principal,
        approval.approval_nonce,
    ) != (
        record["artifact_sha256"],
        record["capture_id"],
        record["source_catalog_sha256"],
        record["source_client_ref"],
        record["source_entry_sha256"],
        record["approval_record_sha256"],
        record["host_principal"],
        record["nonce"],
    ):
        raise TenantRestoreRefused("Existing API-client approval provenance conflicts.")


def acknowledge_client_delivery(
    client_id, *, provenance, delivery_store, host_principal
):
    with transaction.atomic():
        client = ApiClient.objects.select_for_update().get(pk=client_id)
        if client.import_provenance_digest != provenance:
            raise TenantRestoreRefused("API-client delivery provenance changed.")
        if client.credential_delivered_at is None:
            client.credential_delivered_at = timezone.now()
            client.save(update_fields=("credential_delivered_at", "updated_at"))
        delivered_at = client.credential_delivered_at
    # Database acknowledgement is authoritative. If the host write crashes, retry
    # can only finish the tombstone/unlink; it must never reveal the secret again.
    delivery_store.acknowledge(provenance, host_principal=host_principal)
    return delivered_at
