"""Target-owned policy applied before a portable archive may become live.

An archive describes source state.  It is never authority to configure trust on the
target deployment.  This module is intentionally declarative: it neither creates a
makerspace nor inserts imported rows.  The importer consumes these declarations later.
"""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum

from django.apps import apps

from apps.makerspaces.capabilities import default_enabled_features
from apps.makerspaces.models import default_enabled_modules


class RowDisposition(StrEnum):
    DROP = "drop"
    PRESERVE_LIVE = "preserve_live"
    STAGE_INERT = "stage_inert"
    KEEP_TARGET = "keep_target"
    RESOLVE = "resolve"


class ReferenceDisposition(StrEnum):
    DROP_ROW = "drop_row"
    REMAP_RESOLVED = "remap_resolved"
    REMAP_TARGET_MEMBER = "remap_target_member"


@dataclass(frozen=True)
class TargetField:
    value: object = None
    use_model_default: bool = False
    resolver: Callable[[], object] | None = None
    allow_superadmin_override: bool = False
    condition: tuple[str, object] | None = None
    reason: str = ""

    def resolved_value(self, model_label: str, field_name: str):
        # A `resolver` asks the owning registry directly; `use_model_default` reads the
        # column's default. They are NOT interchangeable for capability fields. The test
        # suite patches the `enabled_modules` FIELD DEFAULT to the `everything` profile
        # (see tests/conftest.py), while `default_enabled_modules()` keeps answering the
        # real opt-in set -- so resolving capabilities from the field default would make
        # this projection hand an imported tenant whatever a default happens to say, and
        # would silently grant it every module under the test fixture. Capability policy
        # has one authority, and it is the module registry.
        if self.resolver is not None:
            return self.resolver()
        if self.use_model_default:
            return apps.get_model(model_label)._meta.get_field(field_name).get_default()
        return deepcopy(self.value)


@dataclass(frozen=True)
class RowPolicy:
    disposition: RowDisposition
    reason: str
    condition: tuple[str, object] | None = None


@dataclass(frozen=True)
class SeededResolution:
    lookup_fields: tuple[str, ...]
    archive_update_fields: tuple[str, ...]
    reason: str
    definition_fingerprint_fields: tuple[str, ...] = ()

    def archived_updates(self, archived_row):
        return {
            field: archived_row[field]
            for field in self.archive_update_fields
            if field in archived_row
        }


@dataclass(frozen=True)
class ForeignKeyPolicy:
    disposition: ReferenceDisposition
    reason: str


def _default(reason, *, allow_superadmin_override=False):
    return TargetField(
        use_model_default=True,
        allow_superadmin_override=allow_superadmin_override,
        reason=reason,
    )


TARGET_FIELD_PROJECTION = {
    ("makerspaces.Makerspace", "frontend_domain"): TargetField(
        None, reason="A source domain must not enter the target credentialed-origin allowlist."
    ),
    ("makerspaces.Makerspace", "frontend_domain_status"): _default(
        "Clearing the domain also clears its source verification decision."
    ),
    ("makerspaces.Makerspace", "domain_verified_at"): TargetField(
        None, reason="Source DNS verification is not evidence of target-domain control."
    ),
    ("makerspaces.Makerspace", "frontend_domain_changed_at"): TargetField(
        None, reason="The cleared target domain has no target-side change timestamp."
    ),
    ("makerspaces.Makerspace", "hidden_from_central_directory"): TargetField(
        False, reason="A hidden row without a domain violates ck_makerspace_hidden_requires_domain."
    ),
    ("makerspaces.Makerspace", "superadmin_access_enabled"): TargetField(
        True, reason="Source policy cannot remove the tenant from target superadmin authority."
    ),
    ("makerspaces.Makerspace", "archived_at"): TargetField(
        None, reason="Source lifecycle state cannot make the new target tenant unreachable."
    ),
    ("makerspaces.Makerspace", "resource_limit_overrides"): _default(
        "Resource limits are deployment-owned capacity policy."
    ),
    ("makerspaces.Makerspace", "storage_bytes_used"): TargetField(
        0,
        reason="Target quota accounting starts empty and advances from accepted object bytes.",
    ),
    ("makerspaces.Makerspace", "membership_policy"): TargetField(
        "request", allow_superadmin_override=True,
        reason="Open admission is a target grant, not a portable preference.",
    ),
    ("makerspaces.Makerspace", "referrals_enabled"): TargetField(
        False, allow_superadmin_override=True,
        reason="Referral invitations are a target admission grant.",
    ),
    ("makerspaces.Makerspace", "telegram_group_chat_id"): TargetField(
        "", reason="A source chat id must not receive messages through the target bot."
    ),
    ("makerspaces.Makerspace", "smtp_host"): _default(
        "A source-controlled SMTP relay must not become the target mail connection."
    ),
    ("makerspaces.Makerspace", "smtp_port"): _default(
        "SMTP connection settings are reset as one target-owned unit."
    ),
    ("makerspaces.Makerspace", "smtp_username"): _default(
        "A source SMTP identity must not be used by the target."
    ),
    ("makerspaces.Makerspace", "smtp_use_tls"): _default(
        "Source transport policy is not trusted for a target SMTP connection."
    ),
    ("makerspaces.Makerspace", "smtp_use_ssl"): _default(
        "Source transport policy is not trusted for a target SMTP connection."
    ),
    ("makerspaces.Makerspace", "enabled_modules"): TargetField(
        resolver=default_enabled_modules,
        allow_superadmin_override=True,
        reason="Module installation is target superadmin policy.",
    ),
    ("makerspaces.Makerspace", "enabled_features"): TargetField(
        resolver=default_enabled_features,
        allow_superadmin_override=True,
        reason="Feature installation is target superadmin policy.",
    ),
    ("makerspaces.MakerspaceMembership", "receives_notifications"): _default(
        "Imported memberships start with the target notification default."
    ),
    ("makerspaces.MakerspaceMembership", "role"): TargetField(
        "custom",
        reason="The target Member role has no legacy enum identity; its scalar fallback is CUSTOM.",
    ),
    ("makerspaces.MakerspaceMembership", "can_refer"): _default(
        "Source members cannot carry referral authority into the target."
    ),
    ("makerspaces.MakerspaceMembership", "can_verify"): _default(
        "Source members cannot carry delegated verification authority into the target."
    ),
    ("makerspaces.MembershipRequest", "auto_activate_on_claim"): TargetField(
        False, reason="Claim-time admission must be explicitly re-authorized on the target."
    ),
    ("machines.MachineType", "managing_action"): TargetField(
        "", condition=("is_builtin", False),
        reason="Custom type authorization hooks are server-controlled and normally forced blank."
    ),
    ("integrations.NotificationDestination", "is_active"): TargetField(
        False, condition=("channel", "telegram"),
        reason="Imported Telegram rooms stay inert until a target operator activates them."
    ),
}


ROW_POLICIES = {
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


SEEDED_RESOLUTIONS = {
    "inventory.Category": SeededResolution(
        lookup_fields=("slug",),
        archive_update_fields=("name", "display_order", "icon", "created_at", "updated_at"),
        reason="Resolve seeded placeholders by slug while retaining tenant-edited presentation data.",
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
    ("integrations.NotificationRecipient", "role"): ForeignKeyPolicy(ReferenceDisposition.DROP_ROW, "All explicit recipient rules are dropped."),
    ("machines.RoleMachineScope", "role"): ForeignKeyPolicy(ReferenceDisposition.DROP_ROW, "Role scopes are never remapped to Member."),
    ("machines.RoleMachineTypeScope", "role"): ForeignKeyPolicy(ReferenceDisposition.DROP_ROW, "Role scopes are never remapped to Member."),
    ("machines.Machine", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
    ("machines.MakerspaceMachineTypePricing", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
    ("machines.ServiceQueue", "machine_type"): ForeignKeyPolicy(ReferenceDisposition.REMAP_RESOLVED, "Use the built-in/custom machine type map."),
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
