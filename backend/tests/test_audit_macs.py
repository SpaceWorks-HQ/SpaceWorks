import json
import uuid
from datetime import timedelta
from decimal import Decimal

import logging

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction

from apps.accounts.models import User
from apps.audit.canonical import AuditCanonicalizationError
from apps.audit.keys import (
    AuditMacKeyUnavailable,
    audit_mac_key_cache,
    get_audit_mac_key,
)
from apps.audit.models import AuditLog, AuditMacKey
from apps.audit.verification import AuditMacStatus, classify_audit_row
from apps.audit.services import record
from apps.audit.verification import verify_audit_mac
from tests.audit_mac_helpers import make_space, make_user

pytestmark = pytest.mark.django_db




def test_mac_is_stable_across_database_round_trip():
    actor = make_user("audit-mac-round-trip")
    makerspace = make_space("audit-mac-round-trip")

    row = record(
        actor,
        "audit.round_trip",
        makerspace=makerspace,
        target=makerspace,
        meta={"nested": {"enabled": True, "count": 7}, "labels": ["α", "β"]},
    )
    original_mac = bytes(row.row_mac)

    audit_mac_key_cache.clear()
    row.refresh_from_db()

    assert bytes(row.row_mac) == original_mac
    assert verify_audit_mac(row) is True


@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("makerspace_id", lambda values: values["other_space"].pk),
        ("event_uuid", lambda values: str(uuid.uuid4())),
        ("actor_id", lambda values: values["other_actor"].pk),
        ("action", lambda values: "audit.tampered"),
        ("target_type", lambda values: "inventory.inventoryasset"),
        ("target_id", lambda values: "999999"),
        ("meta", lambda values: {"nested": {"value": 2}}),
        ("created_at", lambda values: values["row"].created_at + timedelta(seconds=1)),
    ],
)
def test_raw_sql_edit_of_any_covered_field_is_detected(column, replacement):
    actor = make_user(f"audit-mac-tamper-{column}")
    other_actor = make_user(f"audit-mac-other-{column}")
    makerspace = make_space(f"audit-mac-tamper-{column}")
    other_space = make_space(f"audit-mac-other-{column}")
    row = record(
        actor,
        "audit.original",
        makerspace=makerspace,
        target=makerspace,
        meta={"nested": {"value": 1}},
    )
    values = {"row": row, "other_actor": other_actor, "other_space": other_space}
    changed_value = replacement(values)

    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = 'replica'")
        try:
            if column == "meta":
                cursor.execute(
                    "UPDATE audit_auditlog SET meta = %s::jsonb WHERE id = %s",
                    [json.dumps(changed_value), row.pk],
                )
            else:
                cursor.execute(
                    f"UPDATE audit_auditlog SET {column} = %s WHERE id = %s",
                    [changed_value, row.pk],
                )
        finally:
            cursor.execute("SET LOCAL session_replication_role = 'origin'")

    row.refresh_from_db()
    assert verify_audit_mac(row) is False


def test_duplicate_payload_uuid_and_mac_is_refused():
    actor = make_user("audit-mac-duplicate")
    makerspace = make_space("audit-mac-duplicate")
    row = record(actor, "audit.original", makerspace=makerspace, meta={"value": 1})

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AuditLog.objects.create(
                actor_id=row.actor_id,
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                makerspace_id=row.makerspace_id,
                meta=row.meta,
                event_uuid=row.event_uuid,
                row_mac=row.row_mac,
                created_at=row.created_at,
            )


@pytest.mark.parametrize("number", [1.0, Decimal("1.0")])
def test_non_integer_numeric_meta_is_rejected(number):
    actor = make_user(f"audit-mac-number-{type(number).__name__.lower()}")
    makerspace = make_space(f"audit-mac-number-{type(number).__name__.lower()}")

    with pytest.raises(AuditCanonicalizationError):
        record(
            actor,
            "audit.invalid_number",
            makerspace=makerspace,
            meta={"value": number},
        )

    assert not AuditLog.objects.filter(action="audit.invalid_number").exists()


def test_global_event_uses_the_null_scope_key():
    actor = make_user("audit-mac-global")

    row = record(actor, "audit.global", meta={"global": True})

    assert AuditMacKey.objects.filter(makerspace=None).count() == 1
    assert row.makerspace_id is None
    assert row.event_uuid is not None
    assert len(bytes(row.row_mac)) == 32
    assert verify_audit_mac(row) is True


def test_write_path_does_not_lazily_recreate_a_missing_scope_key(caplog):
    actor = make_user("audit-mac-no-lazy-key")
    makerspace = make_space("audit-mac-no-lazy-key")
    AuditMacKey.objects.filter(makerspace=makerspace).delete()
    audit_mac_key_cache.invalidate(makerspace.pk)

    # The low-level accessor still fails closed: it must never create a key, because
    # doing so on the write path would take a lock on every audited mutation.
    with pytest.raises(AuditMacKeyUnavailable):
        get_audit_mac_key(makerspace.pk)

    # record() itself must NOT fail closed. It is on every state-changing path, so
    # raising here would stop staff issuing or returning hardware. It degrades to an
    # honestly unattested row and screams in the log instead.
    with caplog.at_level(logging.CRITICAL, logger="apps.audit.services"):
        row = record(actor, "audit.missing_key", makerspace=makerspace)

    assert row.row_mac is None
    assert row.event_uuid is not None
    assert "audit_mac_key_unavailable" in caplog.text
    # Still no lazy creation, and the audit row was not lost.
    assert not AuditMacKey.objects.filter(makerspace=makerspace).exists()
    assert AuditLog.objects.filter(action="audit.missing_key").count() == 1


def test_record_return_value_and_immediate_transaction_insert_are_unchanged():
    actor = make_user("audit-mac-return")
    makerspace = make_space("audit-mac-return")

    with transaction.atomic():
        row = record(actor, "audit.immediate", makerspace=makerspace)
        assert isinstance(row, AuditLog)
        assert row.pk is not None
        assert AuditLog.objects.filter(pk=row.pk).exists()


def test_rolled_back_transaction_leaves_no_audit_row():
    actor = make_user("audit-mac-rollback")
    makerspace = make_space("audit-mac-rollback")
    before = AuditLog.objects.count()

    with pytest.raises(RuntimeError, match="force rollback"):
        with transaction.atomic():
            record(actor, "audit.rolled_back", makerspace=makerspace)
            raise RuntimeError("force rollback")

    assert AuditLog.objects.count() == before
    assert not AuditLog.objects.filter(action="audit.rolled_back").exists()


def test_integer_meta_keys_canonicalize_instead_of_raising():
    """Request acceptance stores {item_pk: quantity}, i.e. INTEGER dict keys.

    Rejecting those would make accepting a hardware request 500. JSONB stores them as
    strings, so the MAC must cover the stringified form that is actually persisted.
    """
    actor = make_user("audit-mac-int-keys")

    row = record(actor, "audit.int_keys", meta={"accepted": {7: 2, 9: 1}})

    assert row.meta["accepted"] == {"7": 2, "9": 1}
    assert verify_audit_mac(row) is True


def test_colliding_meta_keys_are_refused_rather_than_silently_dropped():
    actor = make_user("audit-mac-key-collision")

    with pytest.raises(AuditCanonicalizationError):
        record(actor, "audit.collide", meta={"a": {1: "int", "1": "str"}})


def test_makerspace_creation_succeeds_with_attestation_switched_off(settings):
    """The opt-out path must not break tenant creation.

    The provisioning signal fires on every Makerspace insert; with no master key its
    _fernet() raises ImproperlyConfigured, so an unguarded signal would make creating a
    makerspace impossible on any deployment that has not enabled attestation.
    """
    settings.AUDIT_MAC_MASTER_KEY = ""

    makerspace = make_space("attestation-off-space")

    assert makerspace.pk is not None
    assert not AuditMacKey.objects.filter(makerspace=makerspace).exists()
    row = record(make_user("attestation-off-actor"), "audit.off", makerspace=makerspace)
    assert row.row_mac is None
    assert classify_audit_row(row) is AuditMacStatus.UNATTESTED


@pytest.mark.parametrize(
    "bad_key",
    ["abc", "not!base64!", "a" * 31, "zzzz", "short"],
)
def test_malformed_master_key_degrades_instead_of_crashing(settings, bad_key, caplog):
    """A typo in AUDIT_MAC_MASTER_KEY must not 500 every state-changing request.

    binascii.Error subclasses ValueError, so _fernet()'s handler already converts these,
    but record() is on every audited mutation path -- this pins that end to end rather
    than relying on that inheritance staying true.
    """
    settings.AUDIT_MAC_MASTER_KEY = bad_key
    audit_mac_key_cache.clear()

    with caplog.at_level(logging.CRITICAL, logger="apps.audit.services"):
        row = record(make_user(f"audit-mac-badkey-{abs(hash(bad_key)) % 10000}"), "audit.badkey")

    assert row.pk is not None
    assert row.row_mac is None
    assert "audit_mac_key_unavailable" in caplog.text


def test_makerspace_creation_survives_a_malformed_master_key(settings):
    settings.AUDIT_MAC_MASTER_KEY = "not!base64!"
    audit_mac_key_cache.clear()

    makerspace = make_space("audit-mac-badkey-space")

    assert makerspace.pk is not None
