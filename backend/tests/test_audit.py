import json
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db import Error, transaction

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def make_user(username, role=User.Role.REQUESTER, **kw):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@e.com", role=role, **kw
    )


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def test_record_with_target_model_instance_sets_target_metadata():
    actor = make_user("audit-actor", role=User.Role.SPACE_MANAGER)
    makerspace = make_space("audit-space")

    row = record(
        actor,
        "makerspace.updated",
        makerspace=makerspace,
        target=makerspace,
    )

    assert AuditLog.objects.count() == 1
    row.refresh_from_db()
    assert row.actor == actor
    assert row.action == "makerspace.updated"
    assert row.makerspace == makerspace
    assert row.target_type == makerspace._meta.label_lower
    assert row.target_id == str(makerspace.pk)


def test_record_without_makerspace_or_target_creates_global_row():
    actor = make_user("audit-global", role=User.Role.SUPERADMIN)

    row = record(actor, "system.health_checked")

    assert AuditLog.objects.count() == 1
    row.refresh_from_db()
    assert row.actor == actor
    assert row.makerspace is None
    assert row.target_type == ""
    assert row.target_id == ""


def test_record_fingerprints_email_and_ip_metadata_without_changing_other_fields():
    actor = make_user("audit-sensitive-meta", role=User.Role.SPACE_MANAGER)
    raw_email = "Invitee@Example.test"
    raw_ip = "203.0.113.42"
    actor._claim_audit_context = SimpleNamespace(
        session_id="claim-session",
        issued_by_id=actor.pk,
        redemption_ip=raw_ip,
    )

    row = record(
        actor,
        "membership.invited",
        meta={
            "invite_email": raw_email,
            "origin": raw_ip,
            "outcome": "sent",
            "role_id": 17,
            "email_hash": "a" * 64,
        },
    )

    row.refresh_from_db()
    encoded_meta = json.dumps(row.meta)
    assert raw_email not in encoded_meta
    assert raw_email.lower() not in encoded_meta
    assert raw_ip not in encoded_meta
    assert row.meta["invite_email"].startswith("hmac-sha256:")
    assert row.meta["origin"].startswith("hmac-sha256:")
    assert row.meta["claim_redemption_ip"].startswith("hmac-sha256:")
    assert row.meta["outcome"] == "sent"
    assert row.meta["role_id"] == 17
    assert row.meta["email_hash"] == "a" * 64


def test_audit_log_model_guard_blocks_save_and_delete():
    actor = make_user("audit-guard", role=User.Role.SPACE_MANAGER)
    row = record(actor, "audit.created")

    with pytest.raises(RuntimeError):
        row.save()

    with pytest.raises(RuntimeError):
        row.delete()


def test_audit_log_database_trigger_blocks_update_and_delete():
    actor = make_user("audit-trigger", role=User.Role.SPACE_MANAGER)
    row = record(actor, "audit.triggered")

    with pytest.raises(Error):
        with transaction.atomic():
            AuditLog.objects.filter(pk=row.pk).update(action="x")

    with pytest.raises(Error):
        with transaction.atomic():
            AuditLog.objects.filter(pk=row.pk).delete()
