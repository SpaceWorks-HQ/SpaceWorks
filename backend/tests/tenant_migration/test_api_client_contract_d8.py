from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib
import json
import uuid

import pytest
from django.utils import timezone

from apps.apiclients.models import ApiClient, ApiKeyRequest
from apps.apiclients.scope_registry import ADMIN_READ, PUBLIC_READ, PUBLIC_WRITE
from apps.makerspaces.models import Makerspace
from apps.admin_api import api_client_serializers_clients as serializers_clients
from apps.tenant_migration.host_credential_delivery import CredentialDeliveryStore
from apps.tenant_migration import tenant_restore_api_clients as restore_clients
from apps.tenant_migration.tenant_dump_source_projection import project_makerspace_source
from apps.tenant_migration.tenant_restore_types import TenantRestoreRefused


pytestmark = pytest.mark.django_db
def _catalog_entry(**overrides):
    entry = {
        "source_client_ref": "1" * 64,
        "label": "Source kiosk",
        "client_type": "browser",
        "rate_limit_tier": "standard",
        "is_active": True,
        "stored_scopes": [PUBLIC_READ],
        "stored_origins": ["https://source.example.test"],
        "canonical_scopes": [PUBLIC_READ],
        "canonical_origins": ["https://source.example.test"],
        "eligible_for_reissue": True,
        "ineligibility_reason": "",
    }
    entry.update(overrides)
    entry["source_entry_sha256"] = restore_clients._digest(entry)
    return entry


def _catalog(entry=None):
    entries = [entry or _catalog_entry()]
    return {"entries": entries, "sha256": restore_clients._digest(entries)}
def _approval(catalog, *, capture_id, artifact_sha256="a" * 64, **overrides):
    source = catalog["entries"][0]
    now = timezone.now()
    record = {
        "artifact_sha256": artifact_sha256,
        "capture_id": str(capture_id),
        "source_catalog_sha256": catalog["sha256"],
        "source_client_ref": source["source_client_ref"],
        "source_entry_sha256": source["source_entry_sha256"],
        "label": source["label"],
        "client_type": source["client_type"],
        "rate_limit_tier": source["rate_limit_tier"],
        "target_scopes": [PUBLIC_READ],
        "target_origins": ["https://target.example.test"],
        "privileged_scopes_approved": False,
        "host_principal": "d8-target-operator",
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "nonce": "d8-approval-nonce",
    }
    record.update(overrides)
    record["approval_record_sha256"] = restore_clients._digest(record)
    return record


def _parse(catalog, records, capture_id):
    return restore_clients.parse_approvals(
        {"version": 1, "approvals": records},
        artifact_sha256="a" * 64,
        capture_id=capture_id,
        catalog=catalog,
        now=timezone.now(),
    )


@pytest.mark.xfail(strict=True, reason="SPEC BUG: backend/apps/tenant_migration/tenant_dump_api_clients.py:1 is absent, so Lane D has no source API-client catalog producer.")
def test_source_catalog_exactly_covers_tenant_clients_and_contains_no_secrets():
    source_catalog = importlib.import_module(
        "apps.tenant_migration.tenant_dump_api_clients"
    )
    space = Makerspace.objects.create(name="D8 API catalog", slug="d8-api-catalog")
    other = Makerspace.objects.create(name="D8 other", slug="d8-api-other")
    included = []
    for suffix in ("one", "two"):
        client, _secret = ApiClient.issue(
            label=f"Tenant {suffix}",
            scopes=[PUBLIC_READ],
            makerspace=space,
            allowed_origins=[f"https://{suffix}.example.test"],
            raw_secret=f"d8-current-secret-{suffix}",
        )
        included.append(client)
    ApiClient.issue(
        label="Other tenant", scopes=[PUBLIC_READ], makerspace=other,
        allowed_origins=["https://other.example.test"], raw_secret="other-secret",
    )
    ApiClient.issue(
        label="Global", scopes=[PUBLIC_READ], makerspace=None,
        allowed_origins=["https://global.example.test"], raw_secret="global-secret",
    )
    capture_id = uuid.uuid4()
    deployment_id = uuid.uuid4()
    catalog = source_catalog.build_source_client_catalog(
        capture_id=capture_id,
        source_deployment_id=deployment_id,
        makerspace=space,
    )
    encoded = json.dumps(catalog, sort_keys=True).encode()

    assert len(catalog["entries"]) == 2
    assert {entry["label"] for entry in catalog["entries"]} == {
        client.label for client in included
    }
    def expected_ref(client):
        raw = f"lane-d-source-client-v1\0{capture_id}\0{deployment_id}\0{space.pk}\0{client.pk}"
        return hashlib.sha256(raw.encode()).hexdigest()
    expected_refs = {expected_ref(client) for client in included}
    assert {entry["source_client_ref"] for entry in catalog["entries"]} == expected_refs
    for client in included:
        assert client.client_id.encode() not in encoded
    for forbidden in (
        b"d8-current-secret", b"secret_encrypted", b"previous_secret",
        b"client_id", b"last_seen_ip", b"created_by",
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize("case", ("unknown", "duplicate", "ineligible"))
def test_approval_refuses_unknown_duplicate_and_ineligible_source_refs(case):
    capture_id = uuid.uuid4()
    catalog = _catalog()
    record = _approval(catalog, capture_id=capture_id)
    if case == "unknown":
        record["source_client_ref"] = "2" * 64
        record["approval_record_sha256"] = restore_clients._digest(
            {key: value for key, value in record.items() if key != "approval_record_sha256"}
        )
        records = [record]
    elif case == "duplicate":
        records = [record, deepcopy(record)]
    else:
        catalog = _catalog(_catalog_entry(eligible_for_reissue=False, ineligibility_reason="invalid_scopes"))
        records = [_approval(catalog, capture_id=capture_id)]
    with pytest.raises(TenantRestoreRefused, match="ineligible|duplicated"):
        _parse(catalog, records, capture_id)


@pytest.mark.parametrize("case", ("entry", "catalog"))
def test_approval_refuses_altered_source_or_catalog_digest(case):
    capture_id = uuid.uuid4()
    catalog = _catalog()
    record = _approval(catalog, capture_id=capture_id)
    if case == "entry":
        catalog["entries"][0]["label"] = "altered"
    else:
        catalog["sha256"] = "f" * 64
    with pytest.raises(TenantRestoreRefused, match="digest"):
        _parse(catalog, [record], capture_id)


@pytest.mark.parametrize("field,value", (
    ("label", "Changed label"),
    ("client_type", "server"),
    ("rate_limit_tier", "trusted"),
))
def test_approval_refuses_source_metadata_mismatch(field, value):
    capture_id = uuid.uuid4()
    catalog = _catalog()
    record = _approval(catalog, capture_id=capture_id, **{field: value})
    with pytest.raises(TenantRestoreRefused, match="conflicts"):
        _parse(catalog, [record], capture_id)


def test_approval_refuses_scope_widening_and_noncanonical_origin():
    capture_id = uuid.uuid4()
    catalog = _catalog()
    widened = _approval(catalog, capture_id=capture_id, target_scopes=[PUBLIC_WRITE])
    bad_origin = _approval(
        catalog, capture_id=capture_id, target_origins=["https://target.example.test/path"]
    )

    with pytest.raises(TenantRestoreRefused, match="widens"):
        _parse(catalog, [widened], capture_id)
    with pytest.raises(TenantRestoreRefused, match="scopes or origins"):
        _parse(catalog, [bad_origin], capture_id)


@pytest.mark.parametrize("approved,accepted", ((False, False), (True, True)))
def test_privileged_scope_validation_uses_only_explicit_approval_bit(
    monkeypatch, approved, accepted
):
    capture_id = uuid.uuid4()
    catalog = _catalog(_catalog_entry(canonical_scopes=[ADMIN_READ]))
    record = _approval(
        catalog,
        capture_id=capture_id,
        target_scopes=[ADMIN_READ],
        privileged_scopes_approved=approved,
    )
    calls = []
    original = restore_clients.validate_grantable_scopes

    def observe(scopes, *, privileged):
        calls.append(privileged)
        return original(scopes, privileged=privileged)

    monkeypatch.setattr(restore_clients, "validate_grantable_scopes", observe)
    if accepted:
        assert len(_parse(catalog, [record], capture_id)) == 1
    else:
        with pytest.raises(TenantRestoreRefused, match="scopes or origins"):
            _parse(catalog, [record], capture_id)

    assert calls == [approved]


def test_reissue_conflict_refuses_and_secret_acknowledgement_is_one_way(tmp_path):
    space = Makerspace.objects.create(name="D8 API target", slug="d8-api-target")
    capture_id = uuid.uuid4()
    catalog = _catalog()
    record = _parse(
        catalog, [_approval(catalog, capture_id=capture_id)], capture_id
    )[0]
    store = CredentialDeliveryStore(tmp_path, require_root_owned=False)

    client = restore_clients.reissue_approved_client(
        makerspace=space, record=record, delivery_store=store
    )
    prepared = store.read_unacknowledged(client.import_provenance_digest)
    retried = restore_clients.reissue_approved_client(
        makerspace=space, record=record, delivery_store=store
    )
    assert retried.pk == client.pk
    assert store.read_unacknowledged(client.import_provenance_digest) == prepared

    conflict = dict(record, label="Changed after commit")
    with pytest.raises(TenantRestoreRefused, match="provenance conflicts"):
        restore_clients.reissue_approved_client(
            makerspace=space, record=conflict, delivery_store=store
        )
    assert ApiClient.objects.filter(makerspace=space).count() == 1

    restore_clients.acknowledge_client_delivery(
        client.pk,
        provenance=client.import_provenance_digest,
        delivery_store=store,
        host_principal="d8-target-operator",
    )
    client.refresh_from_db()
    assert client.credential_delivered_at is not None
    restore_clients.reissue_approved_client(
        makerspace=space, record=record, delivery_store=store
    )
    with pytest.raises(TenantRestoreRefused, match="already acknowledged"):
        store.read_unacknowledged(client.import_provenance_digest)


def test_every_ordinary_api_client_input_calls_the_shared_origin_validator(monkeypatch):
    calls = []

    def canonicalize(origins):
        calls.append(tuple(origins))
        return ["https://canonical.example.test"]

    monkeypatch.setattr(serializers_clients, "validate_exact_origins", canonicalize)
    assert serializers_clients.ApiClientSerializer().validate_allowed_origins(
        ["https://client.example.test"]
    ) == ["https://canonical.example.test"]
    assert serializers_clients.ApiKeyRequestSerializer().validate_allowed_origins(
        ["https://request.example.test"]
    ) == ["https://canonical.example.test"]

    assert calls == [
        ("https://client.example.test",),
        ("https://request.example.test",),
    ]


def test_source_api_clients_and_pending_key_requests_do_not_survive_projection():
    space = Makerspace.objects.create(name="D8 API rows", slug="d8-api-rows")
    ApiClient.issue(
        label="Dropped source client", scopes=[PUBLIC_READ], makerspace=space,
        allowed_origins=["https://source.example.test"], raw_secret="dropped-secret",
    )
    ApiKeyRequest.objects.create(
        makerspace=space, label="Pending request", status=ApiKeyRequest.Status.PENDING,
        allowed_origins=["https://pending.example.test"],
    )
    closed = ApiKeyRequest.objects.create(
        makerspace=space, label="Closed history", status=ApiKeyRequest.Status.REJECTED,
        allowed_origins=["https://closed.example.test"],
    )

    projection = project_makerspace_source(space.pk, capture_id=uuid.uuid4())

    assert "apiclients.ApiClient" not in projection.rows
    assert [row["id"] for row in projection.rows["apiclients.ApiKeyRequest"]] == [closed.pk]
