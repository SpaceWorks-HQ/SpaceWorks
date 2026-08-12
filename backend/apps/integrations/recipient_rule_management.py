"""Atomic replacement service for per-event notification recipient rules."""

from django.db import transaction

from apps.audit import services as audit
from apps.integrations.models_recipients import NotificationRecipient


@transaction.atomic
def replace_recipient_rules(*, makerspace, feature, event, rules, keep_row, actor):
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

    existing = NotificationRecipient.objects.filter(
        makerspace=makerspace, feature=feature, event=event
    ).prefetch_related(
        "machine_scopes__machine",
        "machine_type_scopes__machine_type",
        "category_scopes",
    )
    doomed = [row.pk for row in existing if not keep_row(row)]
    NotificationRecipient.objects.filter(pk__in=doomed).delete()

    for rule in rules:
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
        },
    )
