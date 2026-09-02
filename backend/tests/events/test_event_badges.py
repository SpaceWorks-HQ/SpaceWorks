import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.boxes.models import QrCode
from apps.events.models import Event, EventRegistration
from tests.events.checkin_helpers import (
    client_for, make_event, make_member, make_space, make_staff, register,
)


pytestmark = pytest.mark.django_db


def template_url(event):
    return reverse("admin-event-badge-template", kwargs={"pk": event.pk})


def pdf_url(event):
    return reverse("admin-event-badges-pdf", kwargs={"pk": event.pk})


def test_badge_pdf_uses_the_existing_registration_checkin_token(monkeypatch):
    space = make_space("event-badge-token")
    staff = make_staff(space, "badge-staff")
    member = make_member(space, "badge-member", display_name="Badge Person")
    registration = register(make_event(space, "Badge workshop"), member)
    original = registration.checkin_token
    qr_count = QrCode.objects.count()
    captured = {}

    def fake_render(template, snapshots, *, title):
        captured["template"] = template
        captured["snapshots"] = snapshots
        captured["title"] = title
        return b"%PDF-1.4\n% test"

    monkeypatch.setattr("apps.events.views_badges.render_badges_pdf", fake_render)
    response = client_for(staff).post(
        pdf_url(registration.event), {"registration_ids": [registration.pk]}, format="json",
    )
    registration.refresh_from_db()

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Cache-Control"] == "private, no-store"
    assert captured["snapshots"][0].checkin_token == str(original)
    assert registration.checkin_token == original
    assert QrCode.objects.count() == qr_count
    assert not hasattr(registration, "badge_token")
    assert AuditLog.objects.filter(action="event.badges_generated").exists()


def test_badge_eligibility_requires_explicit_attended_opt_in():
    space = make_space("event-badge-status")
    staff = make_staff(space, "badge-status-staff")
    event = make_event(space)
    attended = register(event, make_member(space, "badge-attended"), status=EventRegistration.Status.ATTENDED)
    waitlisted = register(event, make_member(space, "badge-waitlisted"), status=EventRegistration.Status.WAITLISTED)
    client = client_for(staff)

    assert client.post(pdf_url(event), {"registration_ids": [attended.pk]}, format="json").status_code == 409
    assert client.post(pdf_url(event), {
        "registration_ids": [attended.pk], "include_attended": True,
    }, format="json").status_code == 200
    assert client.post(pdf_url(event), {
        "registration_ids": [waitlisted.pk], "include_attended": True,
    }, format="json").status_code == 409


def test_badge_template_is_validated_saved_and_audited():
    space = make_space("event-badge-template")
    staff = make_staff(space, "badge-template-staff")
    event = make_event(space, custom_form=[{
        "id": "diet", "label": "Diet", "type": "short_text", "options": [],
        "required": False,
    }])
    client = client_for(staff)
    initial = client.get(template_url(event))
    saved = client.put(template_url(event), {
        **initial.data, "fields": ["name", "custom:diet", "email"],
    }, format="json")
    invalid = client.put(template_url(event), {
        **initial.data, "fields": ["name", "custom:unknown"],
    }, format="json")

    assert initial.status_code == saved.status_code == 200
    assert saved.data["fields"] == ["name", "custom:diet", "email"]
    assert invalid.status_code == 400
    event.refresh_from_db()
    assert event.badge_template["fields"] == ["name", "custom:diet", "email"]
    assert AuditLog.objects.filter(action="event.badge_template_updated").exists()


def test_badge_endpoints_enforce_tenant_rbac_and_module_on_off():
    space = make_space("event-badge-scope")
    other = make_space("event-badge-outsider")
    staff = make_staff(space, "badge-scope-staff")
    event = make_event(space)
    registration = register(event, make_member(space, "badge-scope-member"))
    other_registration = register(
        make_event(other), make_member(other, "badge-other-member")
    )

    assert client_for(staff).post(
        pdf_url(event), {"registration_ids": [registration.pk]}, format="json",
    ).status_code == 200
    assert client_for(staff).post(
        pdf_url(event), {"registration_ids": [other_registration.pk]}, format="json",
    ).status_code == 404
    assert client_for(make_staff(other, "other-staff")).get(template_url(event)).status_code == 404
    assert APIClient().get(template_url(event)).status_code in (401, 403)
    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=("enabled_modules",))
    assert client_for(staff).get(template_url(event)).status_code == 400
    assert client_for(staff).post(
        pdf_url(event), {"registration_ids": [registration.pk]}, format="json",
    ).status_code == 400
