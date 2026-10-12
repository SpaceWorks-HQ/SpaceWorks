"""Target seed resolution and foreign-key authority policies."""

from .target_projection_types import ForeignKeyPolicy, ReferenceDisposition, SeededResolution


SEEDED_RESOLUTIONS = {
    "inventory.Category": SeededResolution(
        lookup_fields=("slug",),
        archive_update_fields=("name", "display_order", "icon", "loan_days", "max_renewals", "created_at", "updated_at"),
        reason="Resolve seeded placeholders by slug while retaining tenant-edited presentation and loan terms.",
    ),
    "machines.MachineType": SeededResolution(
        lookup_fields=("slug",),
        archive_update_fields=(),
        definition_fingerprint_fields=("name", "icon", "is_builtin", "managing_action", "capability_config"),
        reason="Only an identical global built-in definition may resolve to a target global type.",
    ),
}


FK_POLICIES = {
    ("inventory.InventoryProduct", "category"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the category slug resolution map."),
    ("integrations.DestinationCategoryScope", "category"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the category slug resolution map."),
    ("integrations.RecipientCategoryScope", "category"): ForeignKeyPolicy(ReferenceDisposition.DROP_ROW, "The owning recipient scope is dropped."),
    ("makerspaces.MakerspaceMembership", "assigned_role"): ForeignKeyPolicy(ReferenceDisposition.REMAP_TARGET_MEMBER, "Every imported membership is reduced to the target Member role."),
    ("makerspaces.MembershipRequest", "assigned_role"): ForeignKeyPolicy(ReferenceDisposition.REMAP_TARGET_MEMBER, "Archived requests may reference only the target Member role."),
    ("makerspaces.MembershipVouch", "request"): ForeignKeyPolicy(
        ReferenceDisposition.REMAP_RESOLVED,
        "Remap retained application history; vouches for dropped open applications do not travel.",
    ),
    ("integrations.NotificationRecipient", "role"): ForeignKeyPolicy(ReferenceDisposition.DROP_ROW, "All explicit recipient rules are dropped."),
    ("machines.RoleMachineScope", "role"): ForeignKeyPolicy(ReferenceDisposition.DROP_ROW, "Role scopes are never remapped to Member."),
    ("machines.RoleMachineTypeScope", "role"): ForeignKeyPolicy(ReferenceDisposition.DROP_ROW, "Role scopes are never remapped to Member."),
    ("machines.Machine", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
    ("machines.MachineConsumablePool", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
    ("machines.MakerspaceMachineTypePricing", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
    ("machines.ServiceQueue", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
    ("machines.MakerspaceMachineTypePolicy", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
    ("machines.CertificationType", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
    ("bookings.BookableSpace", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
    ("procurement.ToBuyItem", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
    ("integrations.MachineTypeEmailTemplate", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
    ("integrations.DestinationMachineTypeScope", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
    ("integrations.RecipientMachineTypeScope", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.DROP_ROW, "The owning recipient scope is dropped."),
    ("machines.RoleMachineTypeScope", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.DROP_ROW, "Archived role scopes are dropped even when both targets resolve."),
    ("integrations.RecipientMachineTypeScope", "recipient"): ForeignKeyPolicy(ReferenceDisposition.DROP_ROW, "The parent recipient is dropped."),
    ("integrations.RecipientMachineScope", "recipient"): ForeignKeyPolicy(ReferenceDisposition.DROP_ROW, "The parent recipient is dropped."),
    ("integrations.RecipientCategoryScope", "recipient"): ForeignKeyPolicy(ReferenceDisposition.DROP_ROW, "The parent recipient is dropped."),
}


DROPPED_NOTIFICATION_RECIPIENT_KINDS = frozenset(
    {"role", "requester", "members", "user"}
)

from .projection_wp4 import FK_POLICIES as WP4_FK_POLICIES
FK_POLICIES.update(WP4_FK_POLICIES)
