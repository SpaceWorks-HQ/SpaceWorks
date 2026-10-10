"""Target-owned field defaults; source archives cannot confer trust."""

from apps.makerspaces.capabilities import default_enabled_features
from apps.makerspaces.models import default_enabled_modules

from .target_projection_types import TargetField


def _default(reason, *, allow_superadmin_override=False):
    return TargetField(
        use_model_default=True,
        allow_superadmin_override=allow_superadmin_override,
        reason=reason,
    )


TARGET_FIELD_PROJECTION = {
    ("makerspaces.MakerspaceMembershipSettings", "join_mode"): TargetField(
        "approval", allow_superadmin_override=True,
        reason="Source open or vouch admission cannot grant target membership authority.",
    ),
    ("makerspaces.MakerspaceMembershipSettings", "vouch_replaces_approval"): TargetField(
        False, reason="A target reviewer must authorize admission independently of source vouches.",
    ),
    ("makerspaces.MembershipRequest", "state"): TargetField(
        "canceled", condition=("state", "awaiting_payment"),
        reason="Unsettled debt travels, but its settlement cannot grant source-authorized membership.",
    ),
    ("makerspaces.MembershipRequest", "admission_managed"): TargetField(
        False, reason="Imported application history never activates a membership on payment.",
    ),
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
    ("makerspaces.Station", "created_by"): TargetField(
        None,
        reason="Source provisioning provenance cannot assign a target User.",
    ),
    ("machines.MachineType", "managing_action"): TargetField(
        "", condition=("is_builtin", False),
        reason="Custom type authorization hooks are server-controlled and normally forced blank."
    ),
    ("integrations.NotificationDestination", "is_active"): TargetField(
        False, condition=("channel", "telegram"),
        reason="Imported Telegram rooms stay inert until a target operator activates them."
    ),
    ("evidence.EvidenceRetentionPolicy", "abandoned_upload_cleanup_enabled"): TargetField(
        False, reason="Irreversible abandoned-upload cleanup is a target opt-in."
    ),
    ("evidence.EvidenceRetentionPolicy", "abandoned_upload_retention_days"): TargetField(
        None, reason="The target chooses its own abandoned-upload age."
    ),
    ("evidence.EvidencePhoto", "consumption_state"): TargetField(
        "legacy_unknown", reason="A source consumption marker is never target cleanup proof."
    ),
}

from .target_projection_devices import DEVICE_FIELD_RESETS  # noqa: E402

TARGET_FIELD_PROJECTION.update({
    edge: TargetField(value, reason=reason) for edge, (value, reason) in DEVICE_FIELD_RESETS.items()
})


from .target_projection_7b import printer_projections

TARGET_FIELD_PROJECTION.update(printer_projections(TargetField))

from .target_projection_7c import label_projections

TARGET_FIELD_PROJECTION.update(label_projections(TargetField))
