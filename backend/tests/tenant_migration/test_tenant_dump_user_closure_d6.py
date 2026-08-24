import json
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.data_export.types import Fidelity, SemanticUserRef
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.tenant_migration.models import TenantDumpCapture
from apps.tenant_migration.tenant_dump_derivation import _complete_derivation
from apps.tenant_migration.tenant_dump_database import (
    dump_scratch_database,
    empty_verification_database,
    restore_scratch_dump,
)
from apps.tenant_migration.tenant_dump_errors import TenantDumpClosureRefused
from apps.tenant_migration.tenant_dump_user_closure import (
    _closure,
    build_user_closure,
    reproduce_user_closure,
    verify_closure_digest,
    verify_user_fk_closure,
)
from apps.tenant_migration.tenant_dump_user_closure_manifest import (
    verify_user_closure_manifest,
)
from apps.tenant_migration.tenant_dump_user_rows import apply_user_closure


pytestmark = pytest.mark.django_db


def _space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def _user(name, **values):
    defaults = {
        "username": name,
        "email": f"{name}@example.test",
        "password": "Source password 947!",
        "display_name": f"Display {name}",
        "phone": "+1 555 0100",
        "phone_e164": "+14155550100",
        "is_active": True,
    }
    defaults.update(values)
    return get_user_model().objects.create_user(**defaults)


def _rows(user, *, row_id=701):
    return {"events.EventRegistration": ({"id": row_id, "member_id": user.pk},)}


@pytest.mark.parametrize("status", ("active", "revoked"))
def test_only_exiting_memberships_are_full_including_revoked(status):
    space = _space(f"exclusive-{status}")
    user = _user(f"exclusive-{status}")
    MakerspaceMembership.objects.create(makerspace=space, user=user, status=status)

    closure = build_user_closure(_rows(user), space.pk, "capture-exclusive")

    assert [item["emitted_user_pk"] for item in closure.included] == [user.pk]
    assert closure.stubbed == ()


def test_foreign_or_missing_membership_is_stubbed():
    space = _space("stub-owner")
    foreign = _space("stub-foreign")
    shared = _user("shared-user", phone_e164="+14155550101")
    unjoined = _user("unjoined-user", phone_e164="+14155550102")
    MakerspaceMembership.objects.create(makerspace=space, user=shared)
    MakerspaceMembership.objects.create(
        makerspace=foreign, user=shared, status="revoked"
    )

    closure = build_user_closure(
        {
            "events.EventRegistration": (
                {"id": 1, "member_id": shared.pk},
                {"id": 2, "member_id": unjoined.pk},
            )
        },
        space.pk,
        "capture-stubs",
    )

    assert {item["emitted_user_pk"] for item in closure.stubbed} == {
        shared.pk,
        unjoined.pk,
    }
    assert closure.included == ()


def test_full_and_stub_rows_apply_the_exact_security_projection():
    space = _space("row-projection")
    foreign = _space("row-projection-foreign")
    verified_at = timezone.now()
    full = _user(
        "full-row", is_superuser=True, is_staff=True, role="superadmin",
        telegram_user_id="telegram-full", external_checkin_user_id="checkin-full",
        email_verified_at=verified_at, phone_verified_at=verified_at,
        self_registered_at=verified_at, must_change_password=True,
    )
    stub = _user(
        "stub-row", phone_e164="+14155550103", is_superuser=True, is_staff=True,
        role="superadmin", telegram_user_id="telegram-stub",
    )
    MakerspaceMembership.objects.create(makerspace=space, user=full)
    MakerspaceMembership.objects.create(makerspace=space, user=stub)
    MakerspaceMembership.objects.create(makerspace=foreign, user=stub)
    rows = {
        "events.EventRegistration": (
            {"id": 10, "member_id": full.pk}, {"id": 11, "member_id": stub.pk}
        )
    }
    closure = build_user_closure(rows, space.pk, "capture-row-projection")
    User = get_user_model()
    rows["accounts.User"] = tuple(
        User.objects.filter(pk__in=(full.pk, stub.pk)).order_by("pk").values(
            *(field.attname for field in User._meta.concrete_fields)
        )
    )

    projected = apply_user_closure(rows, closure)
    by_id = {row["id"]: row for row in projected["accounts.User"]}

    assert by_id[full.pk]["password"] == full.password
    assert by_id[full.pk]["email"] == full.email
    assert by_id[full.pk]["phone_e164"] == full.phone_e164
    assert by_id[full.pk]["email_verified_at"] == verified_at
    assert by_id[full.pk]["phone_verified_at"] == verified_at
    assert by_id[full.pk]["self_registered_at"] == verified_at
    assert by_id[full.pk]["must_change_password"] is True
    assert by_id[full.pk]["is_superuser"] is False
    assert by_id[full.pk]["is_staff"] is False
    assert by_id[full.pk]["role"] == "requester"
    assert by_id[full.pk]["telegram_user_id"] == ""
    assert by_id[full.pk]["external_checkin_user_id"] == ""
    assert "groups" not in by_id[full.pk]
    assert "user_permissions" not in by_id[full.pk]
    assert by_id[stub.pk]["username"].startswith("__tenant_stub__")
    assert by_id[stub.pk]["password"].startswith("!")
    assert by_id[stub.pk]["is_tenant_dump_stub"] is True
    assert by_id[stub.pk]["is_active"] is False
    assert by_id[stub.pk]["access_status"] == "suspended"
    assert by_id[stub.pk]["date_joined"].year == 1970
    for field in (
        "first_name", "last_name", "display_name", "email", "phone", "phone_e164",
        "telegram_user_id", "external_checkin_user_id",
    ):
        assert by_id[stub.pk][field] == ""


def test_closure_refusals_are_never_silently_nulled(monkeypatch):
    space = _space("closure-refusals")
    missing_rows = {"events.EventRegistration": ({"id": 1, "member_id": 999999},)}
    with pytest.raises(TenantDumpClosureRefused) as missing:
        build_user_closure(missing_rows, space.pk, "capture-missing")
    assert missing.value.reason_code == "missing_source_user"

    import apps.tenant_migration.tenant_dump_user_closure as closure_module

    changed = dict(closure_module.USER_EDGES)
    changed.pop((Fidelity.PORTABLE, "events.EventRegistration", "member"))
    monkeypatch.setattr(closure_module, "USER_EDGES", changed)
    with pytest.raises(TenantDumpClosureRefused) as unclassified:
        build_user_closure({}, space.pk, "capture-unclassified")
    assert unclassified.value.reason_code == "unclassified_user_edge"

    with pytest.raises(TenantDumpClosureRefused) as dangling:
        verify_user_fk_closure({17: (("events.EventRegistration", 1, "member"),)}, set())
    assert dangling.value.reason_code == "unclosed_non_null_user_edge"


def test_semantic_user_reference_without_rewrite_handler_refuses(monkeypatch):
    import apps.tenant_migration.tenant_dump_user_closure as closure_module

    key = (Fidelity.PORTABLE, "audit.AuditLog", "target_type+target_id")
    changed = dict(closure_module.SEMANTIC_REFERENCES)
    changed[key] = (
        SemanticUserRef("audit.AuditLog", "target_type+target_id", "test semantic edge"),
    )
    monkeypatch.setattr(closure_module, "SEMANTIC_REFERENCES", changed)
    with pytest.raises(TenantDumpClosureRefused) as refused:
        build_user_closure(
            {"audit.AuditLog": ({"id": 1},)}, 1, "capture-semantic"
        )
    assert refused.value.reason_code == "semantic_user_reference_unhandled"


def test_digest_is_reproduced_without_contact_or_foreign_tenant_data(monkeypatch):
    space = _space("digest-space")
    foreign = _space("digest-foreign")
    full = _user("digest-full", phone_e164="+14155550104")
    stub = _user("digest-stub", phone_e164="+14155550105")
    MakerspaceMembership.objects.create(makerspace=space, user=full)
    MakerspaceMembership.objects.create(makerspace=space, user=stub)
    MakerspaceMembership.objects.create(makerspace=foreign, user=stub)
    rows = {
        "events.EventRegistration": (
            {"id": 1, "member_id": full.pk}, {"id": 2, "member_id": stub.pk}
        )
    }
    source = build_user_closure(rows, space.pk, "capture-digest")
    get_user_model().objects.filter(pk=full.pk).update(is_tenant_dump_stub=False)
    get_user_model().objects.filter(pk=stub.pk).update(is_tenant_dump_stub=True)
    import apps.tenant_migration.tenant_dump_user_closure as closure_module
    monkeypatch.setattr(closure_module, "_database_reference_rows", lambda using: rows)

    scratch = reproduce_user_closure("default", "capture-digest")
    target = reproduce_user_closure("default", "capture-digest")

    assert verify_closure_digest(scratch, source.digest) == source.digest
    assert verify_closure_digest(target, source.digest) == source.digest
    assert verify_user_closure_manifest(source.manifest(), "capture-digest") == source.digest
    encoded = json.dumps(source.manifest())
    assert "@example.test" not in encoded
    assert "Source password" not in encoded
    assert "makerspace_id" not in encoded


def test_source_audit_records_only_digest_counts_and_artifact_identity():
    space = _space("closure-audit")
    actor = _user("closure-audit-actor", phone_e164="+14155550107")
    capture = TenantDumpCapture.objects.create(
        makerspace=space,
        requested_by=actor,
        status=TenantDumpCapture.Status.DERIVING,
        source_makerspace_id=space.pk,
        source_makerspace_slug=space.slug,
        superadmin_access_at_decision=True,
        source_encryption_mode=False,
        catalog_digest="a" * 64,
        database_image_sha256="b" * 64,
        object_ledger_sha256="c" * 64,
    )
    closure = _closure((), (), ())
    manifest = {
        "contents": [],
        "user_closure": closure.manifest(),
    }

    _complete_derivation(capture.pk, manifest, "d" * 64)

    event = AuditLog.objects.get(action="tenant_migration.tenant_dump_derived")
    assert event.meta["artifact_id"] == str(capture.pk)
    assert event.meta["capture_id"] == str(capture.pk)
    assert event.meta["user_closure_digest"] == closure.digest
    assert event.meta["user_closure_included_count"] == 0
    assert event.meta["user_closure_stubbed_count"] == 0
    assert event.meta["user_closure_refused_count"] == 0
    assert "included" not in event.meta
    assert "stubbed" not in event.meta
    assert "refused" not in event.meta


@pytest.mark.django_db(transaction=True)
def test_sole_membership_decision_uses_the_immutable_database_image(
    tmp_path, allow_projection_databases
):
    space = _space("immutable-space")
    foreign = _space("immutable-foreign")
    user = _user("immutable-user", phone_e164="+14155550106")
    membership = MakerspaceMembership.objects.create(makerspace=space, user=user)
    image = tmp_path / "immutable-source.dump"
    dump_scratch_database(connection.settings_dict["NAME"], image)

    MakerspaceMembership.objects.create(makerspace=foreign, user=user)
    with empty_verification_database(space.pk, uuid4()) as (using, database_name):
        restore_scratch_dump(image, database_name)
        closure = build_user_closure(
            {"makerspaces.MakerspaceMembership": (
                {"id": membership.pk, "user_id": user.pk},
            )},
            space.pk,
            "capture-immutable",
            using=using,
        )

    assert [item["emitted_user_pk"] for item in closure.included] == [user.pk]
    assert closure.stubbed == ()
