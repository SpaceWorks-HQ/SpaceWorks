"""Audited mutation boundary for event collaboration invitations."""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.audit import services as audit
from apps.makerspaces.guards import require_module_locked
from apps.events.models import Event, EventCollaborator
from apps.makerspaces.models import Makerspace


def _collaborators(event):
    return list(
        EventCollaborator.objects.filter(event=event)
        .select_related("makerspace")
        .order_by("makerspace__slug", "id")
    )


@transaction.atomic
def invite_collaborators(event, *, actor, slugs):
    """Replace an event's invited makerspaces while preserving accepted rows."""
    # Lock order is event first, then makerspaces in primary-key order. publish()
    # uses event-then-makerspace too; reversing these locks creates a deadlock pair.
    locked_event = Event.objects.select_for_update().get(pk=event.pk)
    requested_slugs = set(slugs)
    candidates = list(
        Makerspace.objects.filter(slug__in=requested_slugs).only(
            "id", "slug", "archived_at"
        )
    )
    current_ids = set(
        EventCollaborator.objects.filter(event=locked_event).values_list(
            "makerspace_id", flat=True
        )
    )
    locked_spaces = list(
        Makerspace.objects.select_for_update()
        .filter(
            pk__in={
                locked_event.makerspace_id,
                *current_ids,
                *(row.pk for row in candidates),
            }
        )
        .only("id", "slug", "archived_at")
        .order_by("pk")
    )
    host = next(row for row in locked_spaces if row.pk == locked_event.makerspace_id)
    # The view's `_manageable_event` module check is unlocked. Re-check it now that the
    # host row is held, so a concurrent uninstall cannot slip in and leave collaborator
    # rows created for a module that is off -- the same creation-boundary rule
    # `register()` and `publish()` follow.
    require_module_locked(host.pk, "events")
    if host.slug in requested_slugs:
        raise ValidationError(
            {"slugs": "The host makerspace cannot collaborate on its own event."}
        )
    resolved = {
        row.slug: row
        for row in locked_spaces
        if row.pk != locked_event.makerspace_id and row.archived_at is None
    }
    invalid = sorted(requested_slugs - resolved.keys())
    if invalid:
        raise ValidationError(
            {"slugs": f"Unknown or archived makerspace slug(s): {', '.join(invalid)}."}
        )

    requested_ids = {row.pk for row in resolved.values()}
    EventCollaborator.objects.filter(event=locked_event).exclude(
        makerspace_id__in=requested_ids
    ).delete()
    existing = {
        row.makerspace_id: row
        for row in EventCollaborator.objects.filter(
            event=locked_event,
            makerspace_id__in=requested_ids,
        )
    }
    for makerspace in resolved.values():
        row = existing.get(makerspace.pk)
        if row is None:
            EventCollaborator.objects.create(
                event=locked_event,
                makerspace=makerspace,
                invited_by=actor,
            )
        # A row that is still listed keeps whatever answer it already gave -- accepted AND
        # declined alike. Resetting a declined row to INVITED here looked like "re-invite",
        # but the payload is the whole set: adding one new partner would silently reopen
        # every previously declined invitation and erase who declined and when. Re-inviting
        # someone who said no is a deliberate act, so it goes through remove-then-add.

    resulting_slugs = sorted(resolved)
    audit.record(
        actor,
        "event.collaborators_changed",
        makerspace=host,
        target=locked_event,
        meta={"slugs": resulting_slugs},
    )
    return _collaborators(locked_event)


@transaction.atomic
def remove_collaborator(collaborator_id, *, actor):
    """Delete ONE collaboration row and audit it.

    Deliberately not "rebuild the invited set without this one" via
    `invite_collaborators`: that path validates every remaining slug and rejects archived
    ones, so removing collaborator A would 400 merely because unrelated collaborator B had
    since been archived -- the advertised removal would fail for a reason the operator
    cannot see or act on. Event lock first, then the host, matching every other mutation
    here.
    """
    # Read the event id WITHOUT a row lock first. Locking the collaboration together with
    # its joined event (a `select_for_update().select_related(...)` locks both) would take
    # them in the opposite order to `invite_collaborators`, and a concurrent replace holding
    # the event while waiting on this row deadlocks against this row waiting on the event.
    event_id = (
        EventCollaborator.objects.filter(pk=collaborator_id)
        .values_list("event_id", flat=True)
        .first()
    )
    if event_id is None:
        raise NotFound("This collaboration no longer exists.")
    locked_event = Event.objects.select_for_update().get(pk=event_id)
    locked_row = (
        EventCollaborator.objects.select_for_update()
        .select_related("makerspace")
        .filter(pk=collaborator_id, event=locked_event)
        .first()
    )
    if locked_row is None:
        raise NotFound("This collaboration no longer exists.")
    require_module_locked(locked_event.makerspace_id, "events")
    slug = locked_row.makerspace.slug
    locked_row.delete()
    remaining = sorted(
        EventCollaborator.objects.filter(event=locked_event).values_list(
            "makerspace__slug", flat=True
        )
    )
    audit.record(
        actor,
        "event.collaborators_changed",
        makerspace=locked_event.makerspace,
        target=locked_event,
        meta={"removed": slug, "collaborators": remaining},
    )
    return locked_event


@transaction.atomic
def respond_to_invitation(collaborator, *, actor, accept: bool):
    # Keep the same event-first ordering as invite_collaborators() and publish().
    event = Event.objects.select_for_update().get(pk=collaborator.event_id)
    makerspace = Makerspace.objects.select_for_update().get(
        pk=collaborator.makerspace_id
    )
    try:
        locked = EventCollaborator.objects.select_for_update().get(
            pk=collaborator.pk,
            event=event,
        )
    except EventCollaborator.DoesNotExist:
        # The host can remove the invitation between the view's lookup and this lock.
        # Without this the raced delete surfaces as an untyped 500 rather than the
        # documented 404.
        raise NotFound("This collaboration invitation no longer exists.") from None
    # The collaborator's own module gate, re-checked under its now-locked row.
    require_module_locked(makerspace.pk, "events")
    locked.makerspace = makerspace
    locked.status = (
        EventCollaborator.Status.ACCEPTED
        if accept
        else EventCollaborator.Status.DECLINED
    )
    locked.responded_by = actor
    locked.responded_at = timezone.now()
    locked.save(update_fields=("status", "responded_by", "responded_at"))
    action = (
        "event.collaboration_accepted"
        if accept
        else "event.collaboration_declined"
    )
    audit.record(
        actor,
        action,
        makerspace=makerspace,
        target=locked,
        meta={"event_id": locked.event_id},
    )
    return locked
