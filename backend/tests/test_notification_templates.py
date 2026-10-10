"""Editable templates for the four FabLab streams, and the chat body (N3).

The security assertion is `test_chat_rendering_refuses_requester_content`: chat is
a room, so member-facing wording must never be routable to one. Registry coverage
lives in test_notification_template_registry.py.
"""

import pytest
from django.core.exceptions import ValidationError

from apps.integrations import chat_templates
from apps.integrations.email_templates import render
from apps.integrations.email_templates_registry import (
    get_entry,
    validate_email_template_strings,
)
from apps.integrations.email_templates_registry_fablab import (
    FABLAB_STREAM_KEYS,
    STREAM_FOR_FEATURE,
)
from apps.integrations.models import EmailTemplate
from apps.integrations.models_chat_templates import ChatTemplate
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


# --- editing: a bad variable is refused, not silently blank ---------------------------


def test_an_unclosed_tag_is_a_validation_error():
    with pytest.raises(ValidationError):
        validate_email_template_strings(
            "bookings", "staff", "created", "Subject", "{% if booking.id %}oops", ""
        )


def test_an_unknown_filter_is_a_validation_error():
    with pytest.raises(ValidationError):
        validate_email_template_strings(
            "events", "staff", "published", "Subject", "{{ event.title|nosuchfilter }}", ""
        )


def test_an_unknown_stream_or_key_is_refused():
    with pytest.raises(ValidationError):
        validate_email_template_strings("bookings", "staff", "not_an_event", "s", "t", "")


# --- per-space overrides win, and a broken one falls back ----------------------------


def test_a_space_override_replaces_the_default():
    space = make_space("tmpl-override")
    EmailTemplate.objects.create(
        makerspace=space,
        stream="maintenance",
        audience="staff",
        key="logged",
        subject="Custom: {{ machine.name }}",
        text_body="Machine {{ machine.name }} was serviced.",
    )
    entry = get_entry("maintenance", "staff", "logged")

    result = render(space, "maintenance", "staff", "logged", entry.sample_context)

    assert result["subject"] == "Custom: Laser cutter"
    assert result["text_body"] == "Machine Laser cutter was serviced."


def test_an_inactive_override_falls_back_to_the_default():
    space = make_space("tmpl-inactive")
    EmailTemplate.objects.create(
        makerspace=space,
        stream="events",
        audience="staff",
        key="published",
        subject="Custom",
        text_body="Custom",
        is_active=False,
    )
    entry = get_entry("events", "staff", "published")

    result = render(space, "events", "staff", "published", entry.sample_context)

    # is_active=False means "use the built-in default", never "suppress the email".
    assert result["subject"] != "Custom"
    assert "Laser cutter induction" in result["text_body"]


# --- D1: one chat body, falling back to the adapter's text ---------------------------


def test_chat_falls_back_to_the_payload_text_when_no_row_exists():
    space = make_space("chat-fallback")
    entry = get_entry("maintenance", "staff", "logged")

    text = chat_templates.render_chat_text(
        space, "maintenance", "logged", "adapter text", entry.sample_context
    )

    assert text == "adapter text"


def test_one_chat_row_serves_every_channel():
    space = make_space("chat-shared-body")
    ChatTemplate.objects.create(
        makerspace=space,
        feature="maintenance",
        event="logged",
        text_body="{{ machine.name }} needs attention",
    )
    entry = get_entry("maintenance", "staff", "logged")

    # There is no per-channel body to diverge: the same render feeds Slack, Mattermost,
    # Discord and Telegram.
    text = chat_templates.render_chat_text(
        space, "maintenance", "logged", "adapter text", entry.sample_context
    )

    assert text == "Laser cutter needs attention"


def test_an_inactive_chat_row_falls_back():
    space = make_space("chat-inactive")
    ChatTemplate.objects.create(
        makerspace=space,
        feature="events",
        event="published",
        text_body="custom",
        is_active=False,
    )
    entry = get_entry("events", "staff", "published")

    assert (
        chat_templates.render_chat_text(
            space, "events", "published", "adapter text", entry.sample_context
        )
        == "adapter text"
    )


def test_a_chat_row_that_renders_empty_falls_back_rather_than_posting_nothing():
    space = make_space("chat-empty")
    ChatTemplate.objects.create(
        makerspace=space,
        feature="events",
        event="published",
        text_body="{{ missing_variable }}",
    )
    entry = get_entry("events", "staff", "published")

    assert (
        chat_templates.render_chat_text(
            space, "events", "published", "adapter text", entry.sample_context
        )
        == "adapter text"
    )


def test_a_broken_chat_lookup_falls_back(monkeypatch):
    space = make_space("chat-fail-open")

    def boom(*args, **kwargs):
        raise RuntimeError("chat template table unavailable")

    monkeypatch.setattr(ChatTemplate.objects, "filter", boom)
    entry = get_entry("events", "staff", "published")

    assert (
        chat_templates.render_chat_text(
            space, "events", "published", "adapter text", entry.sample_context
        )
        == "adapter text"
    )


def test_a_chat_body_is_validated_against_the_staff_context():
    with pytest.raises(ValidationError):
        chat_templates.validate_chat_template_string(
            "bookings", "created", "{% if booking.id %}unclosed"
        )
    # The staff entry is what governs, so a staff variable must validate.
    chat_templates.validate_chat_template_string(
        "bookings", "created", "Booking {{ booking.id }} for {{ booking.name }}"
    )


# --- D7: chat is a staff surface -----------------------------------------------------


def test_chat_rendering_refuses_requester_content():
    space = make_space("chat-staff-only")
    entry = get_entry("bookings", "requester", "confirmed")

    with pytest.raises(chat_templates.RequesterContentInChatError):
        chat_templates.render_chat_text(
            space,
            "bookings",
            "confirmed",
            "Your booking is confirmed",
            entry.sample_context,
            audience="requester",
        )


def test_chat_templates_are_only_ever_keyed_to_staff_entries():
    # If this ever resolves a requester entry, an operator could author a chat body from
    # member-facing variables and post it into a shared room.
    assert chat_templates.CHAT_AUDIENCE == "staff"
    for feature, stream in STREAM_FOR_FEATURE.items():
        for key in FABLAB_STREAM_KEYS[stream]:
            entry = chat_templates.chat_entry(feature, key)
            assert entry is get_entry(stream, "staff", key)


def test_a_requester_body_and_a_chat_body_are_built_from_different_templates():
    space = make_space("chat-vs-member")
    requester = get_entry("bookings", "requester", "confirmed")
    staff = get_entry("bookings", "staff", "confirmed")

    member_text = render(
        space, "bookings", "requester", "confirmed", requester.sample_context
    )["text_body"]
    room_text = chat_templates.render_chat_text(
        space,
        "bookings",
        "confirmed",
        render(space, "bookings", "staff", "confirmed", staff.sample_context)["text_body"],
        staff.sample_context,
    )

    assert "Your booking is confirmed" in member_text
    assert "Your booking is confirmed" not in room_text
