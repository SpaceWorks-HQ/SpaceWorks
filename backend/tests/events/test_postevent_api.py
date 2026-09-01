from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.events.models import Event, EventFeedbackResponse, EventRegistration
from apps.events.services_feedback import configure_survey, open_survey
from apps.makerspaces.models import Makerspace
from tests.member_submission import active_member_client


pytestmark = pytest.mark.django_db

QUESTIONS = [{
    "id": "comment",
    "label": "Comment",
    "type": "paragraph",
    "options": [],
    "required": True,
}]


def setup_event(slug="feedback-api", *, public=True, certificate=False):
    space = Makerspace.objects.create(name=slug, slug=slug)
    event = Event.objects.create(
        makerspace=space,
        title="Ended event",
        starts_at=timezone.now() - timedelta(hours=2),
        ends_at=timezone.now() - timedelta(hours=1),
        status=Event.Status.PUBLISHED,
        is_public=public,
    )
    configure_survey(
        event,
        actor=None,
        title="Feedback",
        questions=QUESTIONS,
        certificate_enabled=certificate,
    )
    open_survey(event, actor=None)
    return space, event


def public_url(space, event):
    return reverse(
        "public-event-feedback",
        kwargs={"makerspace_slug": space.slug, "public_token": event.public_token},
    )


def test_public_anonymous_feedback_get_and_post_when_events_module_is_on():
    space, event = setup_event()
    _member, client = active_member_client(space, "feedback-api-member")

    form = client.get(public_url(space, event))
    submitted = client.post(
        public_url(space, event),
        {"answers": {"comment": " Useful "}},
        format="json",
    )

    assert form.status_code == 200
    assert form.data["mode"] == "anonymous"
    assert submitted.status_code == 201
    assert submitted.data["certificate"] is None
    assert EventFeedbackResponse.objects.get().registration_id is None


def test_public_feedback_is_withdrawn_when_events_module_is_off():
    space, event = setup_event("feedback-module-off")
    _member, client = active_member_client(space, "feedback-off-member")
    space.enabled_modules.remove("events")
    space.save(update_fields=["enabled_modules"])

    response = client.get(public_url(space, event))

    assert response.status_code == 400


def test_private_event_does_not_disclose_feedback_by_public_token():
    space, event = setup_event("private-feedback", public=False)
    _member, client = active_member_client(space, "private-feedback-member")

    assert client.get(public_url(space, event)).status_code == 404


def test_public_certificate_endpoint_rejects_registered_no_show():
    space, event = setup_event("api-no-show", certificate=True)
    member, client = active_member_client(space, "api-no-show-member")
    EventRegistration.objects.create(
        event=event,
        member=member,
        name=member.display_name,
        email=member.email,
        phone=member.phone,
        status=EventRegistration.Status.REGISTERED,
    )

    response = client.post(
        public_url(space, event),
        {"email": member.email, "answers": {"comment": "Good"}},
        format="json",
    )

    assert response.status_code == 404
    assert response.data["code"] == "feedback_not_found"
