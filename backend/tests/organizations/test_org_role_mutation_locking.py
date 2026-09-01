import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.machines import role_scope_services
from apps.machines.models import MachineType, RoleMachineTypeScope
from apps.makerspaces import role_services
from apps.makerspaces.models import MakerspaceRole
from apps.organizations.models import (
    Organization,
    OrganizationMakerspace,
    OrganizationMembership,
)
from tests.organizations.test_org_authority import (
    grant,
    link,
    make_makerspace,
    make_organization,
    make_user,
)


pytestmark = pytest.mark.django_db


def _organization_manager(slug):
    makerspace = make_makerspace(f"{slug}-space")
    organization = make_organization(f"{slug}-org")
    actor = make_user(f"{slug}-actor")
    organization_link = link(
        organization,
        makerspace,
        OrganizationMakerspace.Relationship.MANAGER,
    )
    organization_grant = grant(
        organization,
        actor,
        [rbac.Action.MANAGE_MAKERSPACE],
    )
    return makerspace, actor, organization_link, organization_grant


def test_role_mutation_locks_organization_parent_before_child_rows():
    makerspace, actor, _organization_link, _organization_grant = (
        _organization_manager("org-role-lock-order")
    )

    with CaptureQueriesContext(connection) as queries:
        role_services.create_role(
            makerspace=makerspace,
            actor=actor,
            name="Lock order role",
            granted_actions=[],
        )

    expected_tables = [
        Organization._meta.db_table,
        OrganizationMakerspace._meta.db_table,
        OrganizationMembership._meta.db_table,
    ]
    organization_lock_sql = []
    for query in queries.captured_queries:
        sql = query["sql"]
        if "FOR UPDATE" not in sql:
            continue
        # The membership query's not-restored predicate contains a nested FROM
        # OrganizationMakerspace. Classify the row Django actually locks, not every
        # table the authorization query reads while deciding whether it is eligible.
        explicit_target = next(
            (
                table
                for table in expected_tables
                if f'FOR UPDATE OF "{table}"' in sql
            ),
            None,
        )
        base_table = sql.partition('FROM "')[2].partition('"')[0]
        locked_table = explicit_target or base_table
        if locked_table in expected_tables:
            organization_lock_sql.append((locked_table, sql))

    assert [table for table, _ in organization_lock_sql] == expected_tables
    for table, sql in organization_lock_sql:
        assert f'ORDER BY "{table}"."id" ASC' in sql


def _machine_scope_case(slug):
    makerspace, actor, organization_link, organization_grant = (
        _organization_manager(slug)
    )
    machine_type = MachineType.objects.create(
        makerspace=makerspace,
        slug=f"{slug}-type",
        name=f"{slug} type",
    )
    role = MakerspaceRole.objects.create(
        makerspace=makerspace,
        name=f"{slug} machine team",
        slug=f"{slug}-machine-team",
        granted_actions=[rbac.Action.MANAGE_MACHINES],
    )
    client = APIClient()
    client.force_authenticate(actor)
    url = reverse(
        "admin-role-machine-scope",
        args=[makerspace.pk, role.pk],
    )
    return {
        "client": client,
        "url": url,
        "role": role,
        "machine_type": machine_type,
        "organization_link": organization_link,
        "organization_grant": organization_grant,
    }


def _put_scope_after_revocation(monkeypatch, case, revoke):
    original = role_scope_services.set_role_machine_scope

    def revoke_after_view_authorization(**kwargs):
        revoke()
        return original(**kwargs)

    monkeypatch.setattr(
        role_scope_services,
        "set_role_machine_scope",
        revoke_after_view_authorization,
    )
    response = case["client"].put(
        case["url"],
        {
            "machine_type_ids": [case["machine_type"].pk],
            "machine_ids": [],
        },
        format="json",
    )
    assert response.status_code == 403
    assert not RoleMachineTypeScope.objects.filter(role=case["role"]).exists()


def test_machine_scope_write_fails_when_org_grant_is_revoked_after_lookup(
    monkeypatch,
):
    case = _machine_scope_case("org-scope-grant-race")
    _put_scope_after_revocation(
        monkeypatch,
        case,
        case["organization_grant"].delete,
    )


def test_machine_scope_write_fails_when_org_link_is_revoked_after_lookup(
    monkeypatch,
):
    case = _machine_scope_case("org-scope-link-race")
    _put_scope_after_revocation(
        monkeypatch,
        case,
        case["organization_link"].delete,
    )
