"""Import-surface and identity guards for authorization module splits."""

from apps.accounts import rbac, rbac_actions
from apps.machines import role_scope, role_scope_resolution


RBAC_PUBLIC_NAMES = (
    "ALL",
    "ALL_ACTIONS",
    "Action",
    "HANDOUT_ACTIONS",
    "IMPLIED_ACTIONS",
    "ORGANIZATION_GRANTABLE_ACTIONS",
    "ROLE_FORBIDDEN_ACTIONS",
    "ROLE_GRANTABLE_ACTIONS",
    "ROLE_SUPERADMIN_ASSIGNABLE_ACTIONS",
    "actions_for_membership",
    "actions_for_organization_membership",
    "actions_satisfying",
    "archived_makerspace_ids",
    "can",
    "effective_actions",
    "expand_implied_actions",
    "has_any_org_authority",
    "hide_from_superadmin",
    "is_handout_only",
    "is_space_manager_identity",
    "makerspaces_for_action",
    "makerspaces_for_actions",
    "membership_role",
    "resolve_scope",
    "scope_by_action",
    "scope_by_makerspace",
    "scope_by_visibility_or_action",
    "superadmin_hidden_block_applies",
    "superadmin_hidden_makerspace_ids",
)
RBAC_CROSS_MODULE_PRIVATE_NAMES = (
    "_MEMBERSHIP_ROLE_ACTIONS",
    "_exclude_archived_ids",
    "_id_in",
    "_is_superadmin",
    "_membership_for",
    "_organization_authority_memberships",
    "_superadmin_hidden_to_exclude",
)
ROLE_SCOPE_PUBLIC_NAMES = (
    "EXEMPT",
    "NOTHING",
    "SERVICE_REQUEST_MACHINE_PATHS",
    "SERVICE_REQUEST_TYPE_PATHS",
    "covers_machine",
    "covers_service_request",
    "covers_type",
    "grant_builtin_type_scope",
    "grants_directly",
    "is_machine_only",
    "makerspaces_granting_directly",
    "manage_scope_for",
    "manage_scopes_for",
    "manage_scopes_for_memberships",
    "organization_grants_directly",
    "role_grants_directly",
    "scope_covers_machine",
    "scope_covers_type",
    "scope_q_for",
    "scoped_q",
    "scoped_related_q",
    "scoped_service_requests",
)


def test_authorization_barrels_preserve_import_surfaces():
    for name in RBAC_PUBLIC_NAMES + RBAC_CROSS_MODULE_PRIVATE_NAMES:
        assert getattr(rbac, name) is not None
    for name in ROLE_SCOPE_PUBLIC_NAMES:
        assert getattr(role_scope, name) is not None


def test_authorization_sentinels_preserve_leaf_identity():
    assert rbac.ALL is rbac_actions.ALL
    assert role_scope.EXEMPT is role_scope_resolution.EXEMPT
    assert role_scope.NOTHING is role_scope_resolution.NOTHING
