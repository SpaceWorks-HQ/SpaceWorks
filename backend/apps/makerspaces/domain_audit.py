"""Audit entries for a makerspace's frontend domain and /control/ settings edits.

A domain change moves origin trust (CORS, staff sessions, Host validation, TLS), so it
gets its own action rather than hiding inside `makerspace.updated`. Hostnames are
public DNS names, not secrets, and `makerspace.domain_verify_attempt` already records
them, so the before/after pair is safe to keep in append-only metadata.
"""

from apps.audit import services as audit

# /control/ form fields that are not settings: the capability matrix audits itself as
# `makerspace.capabilities_changed`, and image uploads/clears go through the image mixin.
_CONTROL_NON_SETTING_FIELDS = frozenset(
    {"capabilities", "logo_upload", "clear_logo", "cover_upload", "clear_cover"}
)


def record_domain_change(actor, makerspace, previous_domain):
    audit.record(
        actor,
        "makerspace.domain_changed",
        makerspace=makerspace,
        target=makerspace,
        meta={
            "before": previous_domain,
            "after": makerspace.frontend_domain,
            "status": makerspace.frontend_domain_status,
        },
    )


def record_control_save(actor, makerspace, changed_data, *, created):
    """`makerspace.created` / `makerspace.updated` for a /control/ form save.

    Field NAMES only, exactly like the staff API: the form carries free text (name,
    location) that the append-only log has no business keeping.
    """
    if created:
        audit.record(
            actor,
            "makerspace.created",
            makerspace=makerspace,
            target=makerspace,
            meta={"via": "control"},
        )
        return
    fields = sorted(set(changed_data) - _CONTROL_NON_SETTING_FIELDS)
    if fields:
        audit.record(
            actor,
            "makerspace.updated",
            makerspace=makerspace,
            target=makerspace,
            meta={"fields": fields, "via": "control"},
        )
