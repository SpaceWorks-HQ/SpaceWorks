import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.utils import timezone
from icalendar import Calendar

from apps.maintenance.calendar_feed import issue, resolve, render
from apps.maintenance.models_feed import MaintenanceCalendarFeed
from apps.maintenance.models import MaintenanceSchedule
from tests.maintenance.helpers import make_machine_setup
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db


def world(slug, operator_level=None):
    space, actor, machine, operator = make_machine_setup(slug, operator_level=operator_level)
    space.enabled_features = sorted(set(space.enabled_features) | {"maintenance.calendar_feed"})
    space.save(update_fields=["enabled_features"])
    MaintenanceSchedule.objects.create(machine=machine, description="Clean optics\nNo location", interval_days=30, next_due=timezone.localdate())
    return space, actor, machine, operator


def test_hashed_rotation_revocation_and_cross_tenant_token():
    space, actor, _, _ = world("feed-token")
    other, _, _, _ = world("feed-other")
    row, token = issue(actor, space)
    assert token not in str(bytes(row.token_digest)) and len(bytes(row.token_digest)) == 32
    assert resolve(other.pk, token) is None
    _, rotated = issue(actor, space)
    assert resolve(space.pk, token) is None
    client = APIClient()
    client.force_authenticate(actor)
    assert client.delete(reverse("maintenance-feed", kwargs={"makerspace_id": space.pk})).status_code == 204
    assert resolve(space.pk, rotated) is None


def test_feed_scopes_machines_and_rechecks_revoked_operator():
    space, actor, machine, operator = world("feed-scope", "operate")
    from apps.machines.models import Machine, MachineOperator
    hidden = Machine.objects.create(makerspace=space, machine_type=machine.machine_type, name="Unreachable")
    MaintenanceSchedule.objects.create(machine=hidden, description="Private", interval_days=30, next_due=timezone.localdate())
    _, token = issue(operator, space)
    url = reverse("maintenance-feed-calendar", kwargs={"makerspace_id": space.pk, "raw_token": token})
    response = APIClient().get(url)
    assert response.status_code == 200
    events = Calendar.from_ical(response.content).walk("VEVENT")
    assert len(events) == 1 and "Test Machine" in str(events[0]["SUMMARY"])
    assert b"Unreachable" not in response.content
    MachineOperator.objects.filter(machine=machine, user=operator).delete()
    assert APIClient().get(url).status_code == 404


def test_module_off_valid_token_400_unknown_token_404_and_stable_etag():
    space, actor, _, _ = world("feed-module")
    _, token = issue(actor, space)
    url = reverse("maintenance-feed-calendar", kwargs={"makerspace_id": space.pk, "raw_token": token})
    client = APIClient()
    response = client.get(url)
    assert response.status_code == 200 and "private" in response["Cache-Control"]
    assert client.get(url, HTTP_IF_NONE_MATCH=response["ETag"]).status_code == 304
    disable_module(space, "maintenance")
    assert client.get(url).status_code == 400
    assert client.get(url.replace(token, "x"*43)).status_code == 404


def test_bearer_token_is_redacted_from_access_log_sources_after_resolution():
    from django.test import RequestFactory
    from django.http import HttpResponse
    from apps.events.middleware import CalendarFeedLogRedactionMiddleware
    token = "sensitive-feed-token"
    path = f"/api/v1/admin/makerspaces/4/maintenance/feed/{token}.ics"
    request = RequestFactory().get(path)
    request.META["RAW_URI"] = path + "?test=1"
    seen = []
    middleware = CalendarFeedLogRedactionMiddleware(lambda req: seen.append(req.path_info) or HttpResponse())
    middleware(request)
    assert seen == [path]  # Views still resolve the real token.
    for value in (request.path, request.path_info, request.META["PATH_INFO"], request.META["RAW_URI"]):
        assert token not in value and "[redacted]" in value


def test_shipped_proxy_configs_suppress_bearer_feed_access_and_error_logging():
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    for relative in ("frontend/nginx.conf", "docker/allinone/nginx.conf"):
        source = (root/relative).read_text()
        block = next(part.split("}", 1)[0] for part in source.split("location ~ ")
                     if "maintenance/feed" in part.split("{", 1)[0])
        assert "access_log off;" in block and "error_log /dev/null;" in block
