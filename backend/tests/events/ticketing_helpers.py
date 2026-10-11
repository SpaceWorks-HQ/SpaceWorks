from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.events.models import Event
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import core_module_keys
from tests.events.collab_helpers import client_for, make_staff


def event_space(slug="tickets", *, membership=False):
    return Makerspace.objects.create(
        name=slug, slug=slug, public_inventory_enabled=True,
        enabled_modules=sorted(core_module_keys() | {"events"} | ({"membership"} if membership else set())),
        enabled_features=["events.account_registration", "events.invites", "events.ticket_types", "events.promo_codes", "charges.enabled", "charges.events"],
    )


def account(name="attendee"):
    return User.objects.create_user(username=name, email=f"{name}@example.test", display_name=name, phone="12345678", access_status="active")


def open_event(space, audience="accounts", **values):
    starts = timezone.now() + timedelta(days=1)
    return Event.objects.create(makerspace=space, title="Workshop", starts_at=starts, ends_at=starts + timedelta(hours=2),
                                registration_audience=audience, is_public=True, status="published", **values)


def public_url(event, route="public-event-register"):
    return reverse(route, kwargs={"makerspace_slug": event.makerspace.slug, "public_token": event.public_token})


def signup(event, user, **data):
    return client_for(user).post(public_url(event), data, format="json")
