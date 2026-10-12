"""Member renewal and subject-access events, with no personal metadata disclosure."""

from .presentation_catalog_types import P

ENTRIES = (
    P("subject_export.requested", "Personal data export requested"),
    P("subject_export.started", "Personal data export started"),
    P("membership.grace_promised", "Membership grace boundary recorded"),
    P("membership.renewal_checkout_attempted", "Membership renewal checkout attempted", ("attempt",)),
    P("subject_export.failed", "Personal data export failed", ("failure_code",)),
    P("subject_export.download_url_issued", "Personal data export download issued",
      ("expires_in_seconds",)),
    P("membership.renewed", "Membership renewed", ("membership_id", "term_id")),
    P("membership.renewal_retry", "Membership renewal retry", ("attempt",)),
    P("account.profile_updated", "Account profile updated", ("fields",)),
    P("account.session_revoked", "Account session revoked", ("kind", "session_hash")),
    P("membership.renewal_cancelled", "Membership renewal cancelled"),
    P("membership.left", "Member left makerspace"),
)
