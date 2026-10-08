"""Presentation entries: Accounts, authentication, staff and API-client audit actions.

Generated from the audit AST discovery, then reviewed. Every literal action has one
entry; ``permitted`` lists only reviewed non-personal LEAF paths (no names, free
text, secrets, object keys or before/after payloads)."""

from .presentation_catalog_types import P

ENTRIES = (
    P("api_client.created", "Api client created", ("api_key_request_id", "scopes")),
    P("api_client.deleted", "Api client deleted"),
    P("api_client.scopes_changed", "Api client scopes changed", ("previous_scopes", "scopes")),
    P("api_client.secret_rotated", "Api client secret rotated",
      ("grace_window_opened", "previous_secret_valid_until")),
    P("api_client.updated", "Api client updated"),
    P("api_integration.updated", "Api integration updated"),
    P("api_key_request.approved", "Api key request approved", ("api_client_id",)),
    P("api_key_request.created", "Api key request created"),
    P("api_key_request.rejected", "Api key request rejected"),
    P("auth.oidc_browser_attempt_consumed", "Auth oidc browser attempt consumed"),
    P("auth.oidc_browser_attempt_started", "Auth oidc browser attempt started"),
    P("auth.social_identity_linked", "Auth social identity linked"),
    P("auth.social_identity_unlinked", "Auth social identity unlinked"),
    P("member.claim_code_issued", "Member claim code issued"),
    P("member.claim_code_revoked", "Member claim code revoked"),
    P("member.profile_image_cleared", "Member profile image cleared"),
    P("member.profile_image_updated", "Member profile image updated"),
    P("member.profile_updated", "Member profile updated",
      (
          "attended_events_changed",
          "attended_events_shown",
          "certifications_shown",
          "fields",
          "is_visible",
          "visibility_changed",
      )),
    P("member.walk_in_created", "Member walk in created", ("has_email", "has_phone")),
    P("member.walk_in_transitioned", "Member walk in transitioned"),
    P("native_app.revoked", "Native app revoked", ("grants_revoked",)),
    P("staff.created", "Staff created"),
    P("staff.membership_revoked", "Staff membership revoked", ("membership_role",)),
    P("staff.membership_updated", "Staff membership updated"),
    P("staff.role_assigned", "Staff role assigned",
      ("membership_id", "new_role_id", "new_role_slug", "old_role_id")),
    P("superadmin.break_glass_space_manager_created", "Superadmin break glass space manager created",
      ),
    P("superadmin.break_glass_space_manager_password_reset", "Superadmin break glass space manager password reset",
      ),
    P("user.access_restored", "User access restored"),
    P("user.access_restricted", "User access restricted", ("status",)),
    P("user.password_changed", "User password changed"),
    P("user.password_reset", "User password reset"),
    P("user.password_reset_via_email", "User password reset via email", ("method",)),
)
