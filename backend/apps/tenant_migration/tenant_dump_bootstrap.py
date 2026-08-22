"""Narrow target-owned rows created after the raw makerspace root is inserted."""

from django.apps import apps
from django.db import connections
from django.utils import timezone

from apps.makerspaces.roles import DEFAULT_ROLE_DEFINITIONS, MEMBER_ROLE_DEFINITION

from .tenant_dump_errors import TenantDumpVerificationError


def seed_default_roles(using, makerspace_id):
    """Seed current protected defaults without invoking model save/signals."""
    model = apps.get_model("makerspaces.MakerspaceRole")
    connection = connections[using]
    quote = connection.ops.quote_name
    table = quote(model._meta.db_table)
    actions_field = model._meta.get_field("granted_actions")
    now = timezone.now()
    role_ids = {}
    definitions = (*DEFAULT_ROLE_DEFINITIONS, MEMBER_ROLE_DEFINITION)
    with connection.cursor() as cursor:
        for legacy_role, name, actions, *slug_parts in definitions:
            slug = slug_parts[0] if slug_parts else legacy_role
            cursor.execute(
                f"INSERT INTO {table} "
                "(makerspace_id, name, slug, granted_actions, legacy_role, "
                "is_default, is_protected, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, TRUE, TRUE, %s, %s) "
                f"RETURNING {quote(model._meta.pk.column)}",
                [
                    makerspace_id,
                    name,
                    slug,
                    actions_field.get_db_prep_save(sorted(actions), connection),
                    legacy_role,
                    now,
                    now,
                ],
            )
            role_ids[slug] = cursor.fetchone()[0]
    if "member" not in role_ids:
        raise TenantDumpVerificationError("Target Member role was not seeded.")
    _seed_machine_manager_scopes(using, role_ids.get("machine_manager"))
    return role_ids


def _seed_machine_manager_scopes(using, role_id):
    if role_id is None:
        return
    type_model = apps.get_model("machines.MachineType")
    scope_model = apps.get_model("machines.RoleMachineTypeScope")
    connection = connections[using]
    quote = connection.ops.quote_name
    now = timezone.now()
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {quote(type_model._meta.pk.column)} FROM "
            f"{quote(type_model._meta.db_table)} WHERE makerspace_id IS NULL "
            f"ORDER BY {quote(type_model._meta.pk.column)}"
        )
        type_ids = [row[0] for row in cursor.fetchall()]
        for type_id in type_ids:
            cursor.execute(
                f"INSERT INTO {quote(scope_model._meta.db_table)} "
                "(role_id, machine_type_id, created_at) VALUES (%s, %s, %s)",
                [role_id, type_id, now],
            )
