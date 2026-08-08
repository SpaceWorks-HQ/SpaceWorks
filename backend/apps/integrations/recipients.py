"""Resolve who receives a (feature, event) notification.

One entry point, two semantics hidden behind it, so no caller has to know which feature
uses which:

* **hardware_requests / printing** keep the existing mute model untouched
  (`EmailNotificationMute`, default-on, uncheck to mute). Not migrated: those are the
  alerts a space cannot afford to lose, and a backfill that got them wrong would fail
  silently.
* **events / bookings / maintenance / members** use explicit per-event selection, where
  **no rows means today's behaviour** — every membership holding the feature's action.
  Rows become authoritative only once one exists.

Everything fails **open** to the action-based default. A broken selection lookup must not
silence a makerspace's alerts; over-notifying is recoverable, missing a maintenance
warning is not. This is deliberately the opposite of the *access* rules, which fail
closed — do not "fix" one to match the other.
"""

import logging

from apps.integrations.models import NotificationFeature
from apps.integrations.models_recipients import (
    NotificationRecipient,
    NotificationRecipientKind,
)

logger = logging.getLogger(__name__)

# Features whose recipients can be picked per event. The other two are mute-based.
SELECTABLE_FEATURES = frozenset(
    {
        NotificationFeature.EVENTS,
        NotificationFeature.BOOKINGS,
        NotificationFeature.MAINTENANCE,
        NotificationFeature.MEMBERS,
    }
)

# The module that must be installed for a feature's notifications to exist at all. A space
# running inventory and machines but no events must not be offered event recipients, and
# must not resolve any if stale rows exist. `hardware_requests` maps to a core module, so
# it is always present.
FEATURE_MODULES = {
    NotificationFeature.HARDWARE_REQUESTS: "request_workflow",
    NotificationFeature.PRINTING: "printing",
    NotificationFeature.EVENTS: "events",
    NotificationFeature.BOOKINGS: "bookings",
    NotificationFeature.MAINTENANCE: "maintenance",
    NotificationFeature.MEMBERS: "membership",
}


def feature_available(makerspace, feature) -> bool:
    """False when the feature's module is not installed for this makerspace."""
    key = FEATURE_MODULES.get(feature)
    if key is None or makerspace is None:
        return True
    try:
        from apps.makerspaces.platform import module_enabled

        return bool(module_enabled(makerspace, key))
    except Exception:
        # Fail open, as everywhere else here: a capability lookup failure must not mute a
        # space. A genuinely uninstalled module has no domain objects to notify about
        # anyway, so the practical risk of this default is near zero.
        logger.warning(
            "notification_feature_module_check_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
        )
        return True


def selection_rows(makerspace, feature, event):
    """Selected recipients for one (feature, event), or [] when none are selected.

    The module gate lives HERE rather than in front of the whole resolver (D14): stale
    rows for an uninstalled module resolve to nothing, and the caller falls back to the
    action-based default. Gating the resolver instead would mute a space on a capability
    change, which is the one outcome D15 forbids.
    """
    if feature not in SELECTABLE_FEATURES or not event:
        return []
    if not feature_available(makerspace, feature):
        return []
    try:
        return list(
            NotificationRecipient.objects.filter(
                makerspace=makerspace, feature=feature, event=event
            )
            .select_related("role", "user")
            .prefetch_related("machine_scopes", "machine_type_scopes", "category_scopes")
        )
    except Exception:
        logger.warning(
            "notification_recipient_lookup_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
        )
        return []


def has_selection(makerspace, feature, event) -> bool:
    return bool(selection_rows(makerspace, feature, event))


def requester_selected(makerspace, feature, event) -> bool:
    """Whether the subject of the notification was ticked.

    Only meaningful once a selection exists; with no selection the caller's existing
    requester behaviour stands unchanged.
    """
    rows = selection_rows(makerspace, feature, event)
    if not rows:
        return False
    return any(row.kind == NotificationRecipientKind.REQUESTER for row in rows)


def _eligible_memberships(makerspace):
    """Active, notifiable memberships of this makerspace.

    `receives_notifications` is filtered in the QUERY, not in Python: it is the member's
    own opt-out (D5) and it outranks a staff selection, so no branch below can bypass it
    by forgetting the check.
    """
    from apps.accounts.models import User
    from apps.makerspaces.models import MakerspaceMembership

    return (
        MakerspaceMembership.objects.filter(
            makerspace=makerspace,
            status="active",
            receives_notifications=True,
            user__is_active=True,
            user__access_status=User.AccessStatus.ACTIVE,
        )
        .exclude(user__is_superuser=True)
        .exclude(user__role=User.Role.SUPERADMIN)
        .select_related("user", "assigned_role")
        .order_by("id")
    )


def _rule_covers(row, scope) -> bool:
    """Whether a recipient row's own narrowing admits this alert's subject.

    No links means everything — the same default as a chat destination and the OPPOSITE
    of role machine-scope, which fails closed. The asymmetry is deliberate: an unscoped
    *role* must reach nothing (that is an access decision), while an unscoped *rule* is
    simply an operator who did not narrow it.
    """
    machine_ids = {link.machine_id for link in row.machine_scopes.all()}
    type_ids = {link.machine_type_id for link in row.machine_type_scopes.all()}
    category_ids = {link.category_id for link in row.category_scopes.all()}
    if not (machine_ids or type_ids or category_ids):
        return True
    if scope is None:
        # The rule asked for specific subjects and this alert names none, so it cannot
        # be one of them.
        return False
    return (
        (scope.machine_id is not None and scope.machine_id in machine_ids)
        or (scope.machine_type_id is not None and scope.machine_type_id in type_ids)
        or (scope.category_id is not None and scope.category_id in category_ids)
    )


def _role_scope_admits(membership_scopes, membership, scope) -> bool:
    """Whether the recipient's ROLE could reach this alert's machine at all.

    D9's floor, and it applies to `kind=role` rows ONLY. Resolving it is asking "does this
    role's MANAGE_MACHINES grant reach this machine", which is a question about authority
    — meaningful when someone was selected *as a role*, meaningless when they were
    selected as a person. Applying it to the member body or a named individual would make
    those kinds unusable for maintenance alerts, since a plain member holds no machine
    grant at all and would resolve to the fail-closed NOTHING.
    """
    if scope is None or scope.machine_id is None:
        return True
    from apps.machines import role_scope as machine_role_scope

    resolved = membership_scopes.get(membership.pk, machine_role_scope.NOTHING)
    if resolved is machine_role_scope.EXEMPT:
        return True
    type_ids, machine_ids = resolved
    return scope.machine_id in machine_ids or scope.machine_type_id in type_ids


def _selected_memberships(makerspace, rows, scope=None):
    """Memberships matched by a selection, in a stable order.

    Every kind resolves through a MEMBERSHIP of this makerspace — including `user`
    (D4). A notification body carries requester names, machine detail and booking info;
    addressing it to an arbitrary platform account is a hand-operated data leak, and on
    managed hosting it crosses tenants. An external contractor gets a no-action Member
    role first. The role FK is matched by id under a makerspace-scoped queryset, so a
    row pointing at another space's role is inert rather than a leak.

    Composition is `role_scope AND (rule_scope OR all)` (D9) — narrowing only, never
    widening, so a recipient can never be alerted about a machine they would 403 on.
    """
    role_rows = {row.role_id: row for row in rows if row.role_id}
    user_rows = {row.user_id: row for row in rows if row.user_id}
    member_rows = [row for row in rows if row.kind == NotificationRecipientKind.MEMBERS]
    if not (role_rows or user_rows or member_rows):
        return []

    candidates = []
    for membership in _eligible_memberships(makerspace):
        # One row is responsible for each membership's inclusion, and it is the one whose
        # narrowing applies. Members-wide is checked first so a broad tick is not
        # accidentally narrowed by an unrelated per-role rule.
        row = None
        if member_rows:
            row = member_rows[0]
        elif membership.assigned_role_id in role_rows:
            row = role_rows[membership.assigned_role_id]
        elif membership.user_id in user_rows:
            row = user_rows[membership.user_id]
        if row is None:
            continue
        if not _rule_covers(row, scope):
            continue
        candidates.append((membership, row))

    if not candidates:
        return []

    from apps.machines import role_scope as machine_role_scope

    role_selected = [
        membership
        for membership, row in candidates
        if row.kind == NotificationRecipientKind.ROLE
    ]
    membership_scopes = (
        machine_role_scope.manage_scopes_for_memberships(role_selected)
        if role_selected
        else {}
    )
    return [
        membership
        for membership, row in candidates
        if row.kind != NotificationRecipientKind.ROLE
        or _role_scope_admits(membership_scopes, membership, scope)
    ]


def selected_emails(makerspace, feature, event, scope=None) -> list[str]:
    """Addresses for an explicit selection. Assumes has_selection() is True."""
    rows = selection_rows(makerspace, feature, event)
    if not rows:
        return []
    try:
        emails, seen = [], set()
        for membership in _selected_memberships(makerspace, rows, scope):
            email = (membership.user.email or "").strip()
            if not email:
                continue
            normalized = email.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            emails.append(email)
        return emails
    except Exception:
        logger.warning(
            "notification_selected_recipient_resolution_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
            exc_info=True,
        )
        return []


def selected_user_ids(makerspace, feature, event, scope=None) -> list[int]:
    """Push recipients for an explicit selection.

    Native push is a MEMBER channel as well as a staff one (D8) — the mobile form of the
    member's own email — so it is filtered by exactly the same selection and opt-out as
    email rather than by a separate matrix.
    """
    rows = selection_rows(makerspace, feature, event)
    if not rows:
        return []
    try:
        return list(
            dict.fromkeys(
                membership.user_id
                for membership in _selected_memberships(makerspace, rows, scope)
            )
        )
    except Exception:
        logger.warning(
            "notification_selected_push_resolution_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "feature": feature},
            exc_info=True,
        )
        return []
