"""Seeded makerspace role presets and runtime initialization helpers.

**Guest Admin is deliberately absent.** It used to be seeded here as a protected default,
which made every makerspace carry a handover role whether or not it ran a front desk, and
made the one role people most wanted to reshape the one they could not delete. Handover is
now expressed the same way any other local arrangement is: a custom role holding the
handout actions, named whatever the space calls that job. Migration `0052` converted the
existing seeded rows in place, so nobody lost a role or an assignment -- see it for the
full reasoning. `MakerspaceMembership.Role.GUEST_ADMIN` survives in the enum as the frozen
fallback for a membership whose role FK is still null, exactly as `print_manager` does.
"""

DEFAULT_ROLE_DEFINITIONS = (
    ("space_manager", "Space Manager", ["accept_request", "assign_box", "edit_inventory", "issue_direct_loan", "issue_request", "manage_bookings", "manage_events", "manage_machines", "manage_makerspace", "manage_printing", "manage_qr", "reject_request", "return_request", "upload_evidence", "view_audit", "view_inventory"]),
    ("inventory_manager", "Inventory Manager", ["accept_request", "assign_box", "edit_inventory", "issue_direct_loan", "issue_request", "manage_qr", "reject_request", "return_request", "upload_evidence", "view_audit", "view_inventory"]),
    ("machine_manager", "Machine Manager", ["manage_machines"]),
)

MEMBER_ROLE_DEFINITION = (None, "Member", [], "member")


def ensure_default_roles(makerspace):
    """Create missing protected defaults without overwriting administrator edits."""
    from apps.makerspaces.models import MakerspaceRole

    for legacy_role, display_name, granted_actions, *slug_parts in (
        *DEFAULT_ROLE_DEFINITIONS,
        MEMBER_ROLE_DEFINITION,
    ):
        slug = slug_parts[0] if slug_parts else legacy_role
        MakerspaceRole.objects.get_or_create(
            makerspace=makerspace,
            slug=slug,
            defaults={
                "name": display_name,
                "legacy_role": legacy_role,
                "granted_actions": sorted(granted_actions),
                "is_default": True,
                "is_protected": True,
            },
        )
