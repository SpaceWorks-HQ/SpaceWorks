"""Atomic replacement service for per-event notification recipient rules."""

from django.db import transaction

from apps.audit import services as audit
from apps.integrations.models_recipients import NotificationRecipient


@transaction.atomic
def replace_recipient_rules(
    *,
    makerspace,
    feature,
    event,
    rules,
    keep_row,
    actor,
    revalidate=None,
    merge_preserved=None,
):
    """Replace exactly the caller-owned partition and preserve every other row.

    The partition is resolved **inside** this transaction, under the makerspace row lock,
    and `keep_row` is a predicate rather than a precomputed id list. Reading the existing
    rows in the view and passing ids down was a read-then-write race: two concurrent PUTs
    both materialize the rows, the second commits, and the first then deletes a set that
    no longer describes the table — leaving a union of both submissions, or failing the
    recipient uniqueness constraint, instead of applying one complete selection.

    The makerspace lock (not a row lock on the recipients) is what serializes it: the rows
    being replaced do not all exist yet, so there is nothing to lock for the inserts, and
    every other capability mutation in this project already serializes on the makerspace
    row — reusing it keeps the lock ordering consistent rather than introducing a second
    lock that could deadlock against the first.
    """
    from apps.makerspaces.models import Makerspace

    Makerspace.objects.select_for_update().get(pk=makerspace.pk)

    # Authorization, the delegate's reach and the resolved scope targets were all computed
    # in the view, BEFORE this lock. A space manager narrowing that role's machine scope
    # can commit while this PUT waits here, and the request would then delete and insert
    # using reach the actor no longer has. `revalidate` re-resolves it under the lock and
    # raises; the same reason `require_module_locked` re-checks a module here rather than
    # trusting the view's read.
    if revalidate is not None:
        rules = revalidate()

    existing = NotificationRecipient.objects.filter(
        makerspace=makerspace, feature=feature, event=event
    ).prefetch_related(
        "machine_scopes__machine",
        "machine_type_scopes__machine_type",
        "category_scopes",
    )
    kept, doomed = [], []
    for row in existing:
        (kept if keep_row(row) else doomed).append(row)
    NotificationRecipient.objects.filter(pk__in=[row.pk for row in doomed]).delete()

    # Some rows cannot be expressed by delete-then-insert, because a uniqueness constraint
    # allows only ONE of them per event and two callers legitimately share it. The caller
    # hands down a callback that edits such a preserved row in place and reports which rule
    # keys it has already expressed; those are then skipped below rather than inserted into
    # a collision. This module stays generic -- it does not learn what "shared" or "reach"
    # mean, so `apps.integrations` gains no dependency on `apps.admin_api`.
    handled = merge_preserved(kept, rules) if merge_preserved is not None else set()

    for rule in rules:
        if rule["kind"] in handled:
            continue
        row = NotificationRecipient.objects.create(
            makerspace=makerspace,
            feature=feature,
            event=event,
            kind=rule["kind"],
            role_id=rule.get("role_id"),
            user_id=rule.get("user_id"),
            created_by=actor,
        )
        targets = rule["scope_targets"]
        for target in targets["machine_types"]:
            row.machine_type_scopes.create(machine_type=target)
        for target in targets["machines"]:
            row.machine_scopes.create(machine=target)
        for target in targets["categories"]:
            row.category_scopes.create(category=target)

    audit.record(
        actor,
        "notification.recipients_selected",
        makerspace=makerspace,
        target=makerspace,
        meta={
            "feature": feature,
            "event": event,
            "kinds": [rule["kind"] for rule in rules],
            # A merge edits a row the actor does not own, which a plain "replace" entry
            # would not distinguish from having created one. The log is append-only, so it
            # is the surviving evidence of who narrowed a shared policy.
            **({"merged": sorted(handled)} if handled else {}),
        },
    )
