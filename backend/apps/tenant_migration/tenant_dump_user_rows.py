"""D6 full-user/stub row rewriting and stub-linked profile removal."""

from datetime import UTC, datetime
from types import MappingProxyType

from django.apps import apps

from .tenant_dump_errors import TenantDumpClosureRefused
from .object_fields import OBJECT_FIELDS


STUB_SCHEMA_VERSION = 1
STUB_TIMESTAMP = datetime(1970, 1, 1, tzinfo=UTC)


def apply_user_closure(rows, closure):
    result = {label: tuple(values) for label, values in rows.items()}
    stubs = closure.stubbed_user_ids
    rewritten = []
    for source in result.get("accounts.User", ()):
        values = dict(source)
        if source["id"] in stubs:
            values.update(_stub_values(user_ref_from_closure(closure, source["id"])))
        else:
            values.update(
                is_superuser=False,
                is_staff=False,
                role="requester",
                telegram_user_id="",
                external_checkin_user_id="",
                is_tenant_dump_stub=False,
            )
        rewritten.append(MappingProxyType(values))
    result["accounts.User"] = tuple(rewritten)

    stub_memberships = {
        row["id"]
        for row in result.get("makerspaces.MakerspaceMembership", ())
        if row["user_id"] in stubs
    }
    dropped_profiles = {
        row["id"]
        for row in result.get("makerspaces.MemberProfile", ())
        if row["membership_id"] in stub_memberships
    }
    result["makerspaces.MemberProfile"] = tuple(
        row
        for row in result.get("makerspaces.MemberProfile", ())
        if row["id"] not in dropped_profiles
    )
    result["makerspaces.MemberProject"] = tuple(
        row
        for row in result.get("makerspaces.MemberProject", ())
        if row["profile_id"] not in dropped_profiles
    )
    return result


def excluded_stub_profile_object_keys(before, after):
    """Return dropped stub-profile objects unless another carried row uses the key."""
    fields = {
        "makerspaces.MemberProfile": "avatar_key",
        "makerspaces.MemberProject": "image_key",
    }
    removed = set()
    retained = set()
    for label, field in fields.items():
        after_ids = {row["id"] for row in after.get(label, ())}
        for row in before.get(label, ()):
            key = row.get(field)
            if key:
                if row["id"] not in after_ids:
                    removed.add(key)
    for label, rows in after.items():
        model = apps.get_model(label)
        object_names = {
            field.attname
            for field in model._meta.concrete_fields
            if field.name in OBJECT_FIELDS
        }
        retained.update(
            row[name]
            for row in rows
            for name in object_names
            if row.get(name)
        )
    return frozenset(removed - retained)


def user_ref_from_closure(closure, pk):
    for item in (*closure.included, *closure.stubbed, *closure.refused):
        if item["emitted_user_pk"] == pk:
            return item["user_ref"]
    raise TenantDumpClosureRefused(
        "A projected user has no closure entry.", reason_code="unclassified_user"
    )


def _stub_values(ref):
    return {
        "username": f"__tenant_stub__{ref}",
        "password": f"!tenant-dump-stub-v{STUB_SCHEMA_VERSION}:{ref}",
        "first_name": "",
        "last_name": "",
        "display_name": "",
        "email": "",
        "phone": "",
        "phone_e164": "",
        "email_verified_at": None,
        "phone_verified_at": None,
        "self_registered_at": None,
        "last_login": None,
        "date_joined": STUB_TIMESTAMP,
        "external_checkin_user_id": "",
        "telegram_user_id": "",
        "is_superuser": False,
        "is_staff": False,
        "is_active": False,
        "is_walk_in": False,
        "must_change_password": False,
        "access_status": "suspended",
        "restriction_reason": "",
        "role": "requester",
        "is_tenant_dump_stub": True,
    }
