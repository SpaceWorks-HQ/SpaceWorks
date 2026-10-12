"""Bearer feeds bind a real user; every read rechecks that user's current scope."""

import hashlib
import re
import secrets
from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit.services import record
from apps.machines import access
from apps.machines.models import Machine
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import feature_enabled
from apps.makerspaces.servability import is_servable
from .models import MaintenanceSchedule
from .models_feed import MaintenanceCalendarFeed


def scope(actor, space):
    rows = rbac.scope_by_makerspace(actor, Machine.objects.all()).filter(makerspace=space, is_active=True)
    return access.scope_machines_for_actor(actor, rows)


def feed_space(actor, pk):
    space = get_object_or_404(rbac.scope_by_makerspace(actor, Makerspace.objects.all(),
                               makerspace_field="id"), pk=pk)
    if not actor.is_active or actor.access_status != "active" or not is_servable(space):
        raise PermissionDenied()
    require_module(space, "maintenance")
    require_module(space, "machines")
    if not feature_enabled(space, "maintenance.calendar_feed"):
        raise ValidationError({"detail": "Maintenance calendar feed is disabled."})
    if not scope(actor, space).exists():
        raise PermissionDenied()
    return space


@transaction.atomic
def issue(actor, space):
    # Serialize first issue as well as rotations on the tenant row.
    rbac.scope_by_makerspace(actor, Makerspace.objects.select_for_update(),
                            makerspace_field="id").get(pk=space.pk)
    feed_space(actor, space.pk)
    token = secrets.token_urlsafe(32)
    row, _ = rbac.scope_verified_tenant(MaintenanceCalendarFeed.objects.all(), space).update_or_create(makerspace=space, user=actor,
        defaults={"token_digest": hashlib.sha256(token.encode("ascii")).digest(),
                  "token_hint": token[-8:], "revoked_at": None})
    record(actor, "maintenance.feed_rotated", makerspace=space, target=row)
    return row, token


@transaction.atomic
def revoke(actor, space):
    row = rbac.scope_verified_tenant(MaintenanceCalendarFeed.objects.select_for_update(), space).filter(user=actor).first()
    if row and row.revoked_at is None:
        row.revoked_at = timezone.now()
        row.save(update_fields=["revoked_at"])
        record(actor, "maintenance.feed_revoked", makerspace=space, target=row)


def resolve(pk, token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token or ""):
        return None
    return rbac.scope_verified_tenant(
        MaintenanceCalendarFeed.objects.select_related("user", "makerspace"), pk,
    ).filter(token_digest=hashlib.sha256(token.encode("ascii")).digest(),
        revoked_at__isnull=True,
    ).first()


def render(actor, space):
    from icalendar import Calendar, Event
    calendar = Calendar()
    calendar.add("prodid", "-//SpaceWorks//Maintenance//EN")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", f"{space.name} maintenance")
    rows = rbac.scope_by_makerspace(actor, MaintenanceSchedule.objects.select_related("machine"),
                                    makerspace_field="machine__makerspace_id").filter(
        machine__in=scope(actor, space), is_active=True, trigger__in=("days", "both"),
    ).order_by("pk")
    for row in rows:
        event = Event()
        event.add("uid", f"maintenance-{space.pk}-{row.pk}@spaceworks")
        event.add("dtstamp", row.updated_at)
        event.add("last-modified", row.updated_at)
        event.add("dtstart", row.next_due)
        event.add("dtend", row.next_due+timedelta(days=1))
        event.add("summary", f"{row.machine.name}: maintenance")
        event.add("description", row.description)
        calendar.add_component(event)
    # Usage-only thresholds have no calendar date; do not invent an ETA.
    return calendar.to_ical()
