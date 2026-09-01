"""Merging a delegate's scope links into a recipient row they do not own.

`uniq_notification_recipient_special` is ``(makerspace, feature, event, kind)``, so exactly
one ``requester`` / ``members`` row may exist per event. Those two kinds name no identity at
all -- ``requester`` is whoever raised the alert, ``members`` is everybody -- so two teams
wanting "notify the requester for MY machines" are both describing the same single row, and
there is no second row for the second team to have.

Delete-then-insert therefore cannot express it: the delegate's insert trips the constraint
and surfaces as a misleading "a Space Manager-managed policy already uses one of these
recipients". Refusing the kinds outright was tried and reverted -- it removes a capability
the design intends. What is left is to treat that one row as **shared**, and to let each
delegate replace only the links inside their own reach.

The predicate that decides which links are the delegate's is :func:`owns_link`, and it is
deliberately the *only* answer to that question: `recipient_rule_access.project_special_row`
shows a delegate exactly the links this module would strip. If "which links do I show you"
and "which links do I strip" could disagree, a round-trip of an unmodified form would
silently add or drop coverage.
"""

from apps.admin_api.recipient_rule_common import RuleValidationError
from apps.integrations.models_recipients import (
    NotificationRecipientKind,
    RecipientCategoryScope,
    RecipientMachineScope,
    RecipientMachineTypeScope,
)

# The two identity-free kinds. Only these are shared, because only these are constrained to
# one row per event -- a role or user row is keyed by its target and each team gets its own.
SHARED_KINDS = frozenset(
    {NotificationRecipientKind.REQUESTER, NotificationRecipientKind.MEMBERS}
)


def owns_link(link, reach, *, kind):
    """Whether `link` is a scope link this delegate may replace.

    `kind` is the link table: ``"machine_type"``, ``"machine"`` or ``"category"``.

    A category link is **never** owned. `manage_scope_for` grants no category reach, so
    there is nothing to check one against and the fail-closed answer is the only safe one --
    the same reason `row_fully_reachable` refuses a row carrying any category link.
    """
    if kind == "machine_type":
        return link.machine_type_id in reach.type_ids
    if kind == "machine":
        return reach.covers_machine(link.machine)
    return False


def owned_links(row, reach):
    """This row's machine-type and machine links, narrowed to the ones the delegate owns.

    Category links are deliberately absent from the result: they are never owned, so they
    are never stripped and never projected.
    """
    return (
        [
            link
            for link in row.machine_type_scopes.all()
            if owns_link(link, reach, kind="machine_type")
        ],
        [
            link
            for link in row.machine_scopes.all()
            if owns_link(link, reach, kind="machine")
        ],
    )


def merge_preserved_for(reach):
    """Build the `merge_preserved` callback `replace_recipient_rules` invokes under the lock.

    Returns a callable ``(preserved_rows, rules) -> handled_keys``. The service skips
    creating any rule whose key comes back, because this callback has already expressed it
    by editing the shared row instead.
    """

    def merge_preserved(preserved_rows, rules):
        submitted = {
            rule["kind"]: rule for rule in rules if rule["kind"] in SHARED_KINDS
        }
        handled = set()

        for row in preserved_rows:
            if row.kind not in SHARED_KINDS:
                continue
            rule = submitted.get(row.kind)
            handled.add(row.kind)

            # A row with NO links covers EVERYTHING -- it is a space-wide policy, and
            # `recipient_scope_matching.rule_covers` reads absent links as "matches every
            # subject". Stripping does nothing to it, and ADDING this delegate's links would
            # silently narrow somebody else's space-wide policy down to one team's machines.
            # So: submitting the kind is refused, and omitting it leaves the row untouched.
            # A silent 200 was rejected -- the delegate's next GET would not show the row,
            # which reads exactly like a save that was dropped.
            if not _has_any_link(row):
                if rule is not None:
                    raise RuleValidationError(
                        "A space-wide policy already covers this recipient. "
                        "Ask a Space Manager to narrow it before scoping it to your machines."
                    )
                continue

            _replace_owned_links(row, rule, reach)

        return handled

    return merge_preserved


def _has_any_link(row):
    return bool(
        row.machine_type_scopes.all()
        or row.machine_scopes.all()
        or row.category_scopes.all()
    )


def _replace_owned_links(row, rule, reach):
    """Strip this delegate's links from `row`, then add the submitted ones back."""
    type_links, machine_links = owned_links(row, reach)
    for link in type_links:
        link.delete()
    for link in machine_links:
        link.delete()

    if rule is not None:
        targets = rule["scope_targets"]
        # Every target here was already validated against this delegate's reach by
        # `_resolve_targets`, and every in-reach link was just removed, so neither
        # `uniq_recipient_machine_type_scope` nor `uniq_recipient_machine_scope` can trip.
        # `get_or_create` keeps that true if a future caller relaxes either assumption.
        for target in targets["machine_types"]:
            row.machine_type_scopes.get_or_create(machine_type=target)
        for target in targets["machines"]:
            row.machine_scopes.get_or_create(machine=target)

    # UNREACHABLE BY CONSTRUCTION, kept as a fail-safe. A row reaches this function only
    # because `row_fully_reachable` said False, and for a shared-kind row the only remaining
    # reasons are an out-of-reach link, a cross-tenant link or a category link -- none of
    # which `owns_link` claims, so at least one always survives the strip above. If that ever
    # stops holding, the row MUST be deleted rather than left behind: no links means
    # EVERYTHING, so a linkless leftover would silently promote one team's narrow rule into a
    # space-wide policy. `test_stripping_the_last_link_deletes_the_row` drives this helper
    # directly, because no API path can reach it.
    if not _links_remain(row):
        row.delete()


def _links_remain(row):
    """Does this row still carry any scope link, according to the DATABASE?

    **Queried through the link models, not through `row.machine_type_scopes`.** The service
    hands these rows over `prefetch_related`, and a related manager whose cache is populated
    answers `.count()` and `.exists()` from that cache -- which still lists the links deleted
    moments earlier. The check would then read "1 remaining" for a row that has none, and the
    guard below would never fire. This is the exact trap the plan warned about, and using
    `.count()` walked into it anyway because it looks like a query.
    """
    return (
        RecipientMachineTypeScope.objects.filter(recipient=row).exists()
        or RecipientMachineScope.objects.filter(recipient=row).exists()
        or RecipientCategoryScope.objects.filter(recipient=row).exists()
    )
