"""Stable import surface for audited, locked makerspace role services."""
from apps.audit import services as audit  # noqa: F401 - existing test patch surface
from apps.makerspaces.role_authority import (  # noqa: F401
    MEMBER_ROLE_SLUG,
    RoleConflict,
    _clean_actions,
    _locked_actor_actions,
    _locked_organization_actions,
    _superadmin,
    _validate_actions,
)
from apps.makerspaces.role_assignments import assign_role, can_assign_role  # noqa: F401
from apps.makerspaces.role_crud import _slug_for, create_role, delete_role, update_role  # noqa: F401
