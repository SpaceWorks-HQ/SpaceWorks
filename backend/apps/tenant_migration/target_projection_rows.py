"""Explicit target row dispositions, including source-local coordination."""

from .target_projection_types import RowDisposition, RowPolicy


ROW_POLICIES = {
    "notifications.MemberNotificationPreference": RowPolicy(RowDisposition.DROP, "Personal delivery policy is target-owned."),
    "notifications.NotificationInboxRow": RowPolicy(RowDisposition.DROP, "Source inbox text and read state are delivery telemetry."),
    "integrations.EmailSuppression": RowPolicy(RowDisposition.DROP, "Deployment-keyed suppressed addresses do not travel."),
    "operations.ReminderSchedule": RowPolicy(
        RowDisposition.DROP,
        "Source-local reminder coordination is rebuilt by target sources; claims never travel.",
    ),
    "makerspaces.Station": RowPolicy(
        RowDisposition.STAGE_INERT,
        "Portable Station metadata has no credential and contributes no live authority edges.",
    ),
    "machines.MachineOperator": RowPolicy(
        RowDisposition.PRESERVE_LIVE,
        "Owner decision 22: preserve the exact live machine grant and provenance.",
    ),
    "makerspaces.MakerspaceRole": RowPolicy(RowDisposition.KEEP_TARGET, "Target-seeded roles are authoritative; archived role rows are dropped."),
    "machines.RoleMachineScope": RowPolicy(RowDisposition.DROP, "Archived role scope would rewrite target machine authority."),
    "machines.RoleMachineTypeScope": RowPolicy(RowDisposition.DROP, "Archived scopes can both grant authority and collide with seeded scopes."),
    "integrations.NotificationRecipient": RowPolicy(RowDisposition.DROP, "Every explicit recipient kind is a live disclosure rule."),
    "integrations.RecipientMachineTypeScope": RowPolicy(RowDisposition.DROP, "A child of a dropped recipient cannot arrive live."),
    "integrations.RecipientMachineScope": RowPolicy(RowDisposition.DROP, "A child of a dropped recipient cannot arrive live."),
    "integrations.RecipientCategoryScope": RowPolicy(RowDisposition.DROP, "A child of a dropped recipient cannot arrive live."),
    "operations.ReportSchedule": RowPolicy(RowDisposition.DROP, "A scheduled report delivery is a live disclosure rule the target must re-create."),
    "integrations.NotificationDestination": RowPolicy(
        RowDisposition.STAGE_INERT,
        "Imported Telegram rooms require target-authorized activation.",
        condition=("channel", "telegram"),
    ),
    # Open source-authored requests/invitations are target admission capability.
    # Dropping both open states prevents a later claim/approval from granting target
    # membership; active/revoked history may still import.
    "makerspaces.MembershipRequest": RowPolicy(
        RowDisposition.DROP,
        "Imported invitations are authority the target never authorized and must be re-created.",
        condition=("state", frozenset({"requested", "invited"})),
    ),
}

