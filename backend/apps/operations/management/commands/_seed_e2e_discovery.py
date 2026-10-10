"""Real discovery and member fixtures for the browser accessibility gate."""

from datetime import timedelta

from django.utils import timezone

from apps.bookings.models import BookableSpace
from apps.events.models import Event
from apps.makerspaces.module_install import install_module


def seed_discovery(makerspace, actor, member):
    for key in ("events", "bookings", "membership"):
        install_module(makerspace, key, actor=actor)
    member.email_verified_at = timezone.now()
    member.save(update_fields=["email_verified_at"])
    makerspace.theme_config = {"primary_color": "#f3c3dd", "accent_color": "#5a1633"}
    makerspace.branding_config = {
        "support_email": "help@example.com",
        "support_url": "https://example.com/support",
    }
    makerspace.save(update_fields=["theme_config", "branding_config"])
    starts_at = timezone.now() + timedelta(days=7)
    event = Event.objects.create(
        makerspace=makerspace, title="E2E Public Workshop", description="Learn together.",
        starts_at=starts_at, ends_at=starts_at + timedelta(hours=2),
        is_public=True, status=Event.Status.PUBLISHED, capacity=10, created_by=actor,
    )
    space = BookableSpace.objects.create(
        makerspace=makerspace, name="E2E Public Bench", is_public=True, capacity=2,
    )
    return {"event_title": event.title, "bookable_space": space.name}
