"""Registry sample and coverage checks, split from template-editing tests."""

import pytest

from apps.integrations.email_templates_registry import (
    STREAMS, get_entry, iter_entries, validate_email_template_strings,
)
from apps.integrations.email_templates_registry_fablab import FABLAB_STREAM_KEYS, STREAM_FOR_FEATURE
from apps.integrations.models import EmailTemplate

pytestmark = pytest.mark.django_db


FABLAB_ENTRIES = [
    (stream, audience, key)
    for stream, keys in FABLAB_STREAM_KEYS.items()
    for key in keys
    for audience in ("staff", "requester")
]


# --- D6: 26 events x both audiences, all rendering -----------------------------------


def test_the_registry_covers_twenty_six_events_in_both_audiences():
    assert sum(len(keys) for keys in FABLAB_STREAM_KEYS.values()) == 26
    assert len(FABLAB_ENTRIES) == 52
    for coordinates in FABLAB_ENTRIES:
        assert get_entry(*coordinates) is not None, coordinates


@pytest.mark.parametrize("stream,audience,key", FABLAB_ENTRIES)
def test_every_entry_renders_against_its_own_sample_context(stream, audience, key):
    entry = get_entry(stream, audience, key)
    validate_email_template_strings(
        stream, audience, key, entry.default_subject, entry.default_text, entry.default_html
    )


def test_every_registry_entry_anywhere_still_renders():
    """The whole registry, not just the new half — the defaults are the fallback path."""
    for (stream, audience, key), entry in iter_entries():
        validate_email_template_strings(
            stream,
            audience,
            key,
            entry.default_subject,
            entry.default_text,
            entry.default_html,
        )


def test_defaults_are_not_blank():
    for coordinates in FABLAB_ENTRIES:
        entry = get_entry(*coordinates)
        assert entry.default_subject.strip(), coordinates
        assert entry.default_text.strip(), coordinates
        assert entry.fields, coordinates


def test_new_streams_are_selectable_on_the_model_and_in_the_registry():
    model_streams = {value for value, _ in EmailTemplate.Stream.choices}
    assert model_streams == STREAMS
    assert set(FABLAB_STREAM_KEYS) <= model_streams


def test_the_members_feature_maps_to_the_membership_stream():
    # The one pair where the feature key and the stream name differ. A render call that
    # assumed they were equal would raise KeyError at send time.
    assert STREAM_FOR_FEATURE["members"] == "membership"
    assert get_entry("membership", "staff", "member_joined") is not None


