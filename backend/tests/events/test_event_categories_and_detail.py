import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.events.models import EventCategory
from apps.events import services
from tests.events.collab_helpers import make_staff, client_for
from tests.events.ticketing_helpers import event_space, open_event, public_url

pytestmark = pytest.mark.django_db


def test_public_detail_categories_and_tags_do_not_expose_private_registration_data():
    space = event_space()
    category = EventCategory.objects.create(makerspace=space, name="Workshops", slug="workshops")
    event = open_event(space, category=category, tags=["wood"])
    other = open_event(space)
    client = APIClient()
    detail = client.get(public_url(event, "public-event-detail"))
    assert detail.status_code == 200
    assert detail.data["category"] == {"id": category.pk, "name": "Workshops", "slug": "workshops"}
    assert detail.data["tags"] == ["wood"]
    assert not {"registrations", "invites", "promo_codes", "created_by_id"} & set(detail.data)
    listing = client.get(reverse("public-event-list", args=[space.slug]), {"category": "workshops", "tag": "wood"})
    assert [row["public_token"] for row in listing.data] == [str(event.public_token)]


@pytest.mark.parametrize("state", ["private", "draft", "cancelled", "wrong_tenant", "unknown"])
def test_public_detail_enumeration_safe_404(state):
    from uuid import uuid4
    space = event_space()
    event = open_event(space)
    if state == "private":
        event.is_public = False
    elif state in {"draft", "cancelled"}:
        event.status = state
    event.save()
    url = public_url(event, "public-event-detail")
    if state == "wrong_tenant":
        other = event_space("other")
        url = url.replace(space.slug, other.slug)
    elif state == "unknown":
        url = url.replace(str(event.public_token), str(uuid4()))
    assert APIClient().get(url).status_code == 404


def test_module_off_detail_returns_400_and_foreign_category_is_refused():
    space, other = event_space(), event_space("other")
    event = open_event(space)
    foreign = EventCategory.objects.create(makerspace=other, name="Other", slug="other")
    from rest_framework.exceptions import NotFound
    with pytest.raises(NotFound):
        services.update_event(event, actor=make_staff(space), category_id=foreign.pk)
    space.enabled_modules.remove("events")
    space.save(update_fields=["enabled_modules"])
    assert APIClient().get(public_url(event, "public-event-detail")).status_code == 400


def test_staff_category_create_is_scoped_and_audited():
    from apps.audit.models import AuditLog
    space, other = event_space(), event_space("other")
    staff, foreign = make_staff(space), make_staff(other)
    url = reverse("admin-event-categories", args=[space.pk])
    assert client_for(foreign).post(url, {"name": "Wood", "slug": "wood"}, format="json").status_code == 404
    response = client_for(staff).post(url, {"name": "Wood", "slug": "wood"}, format="json")
    assert response.status_code == 201
    assert AuditLog.objects.filter(actor=staff, action="event.category_created").exists()
