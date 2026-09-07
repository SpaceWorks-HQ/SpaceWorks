import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.hardware_requests.models import HardwareRequest
from tests.return_helpers import make_accepted_request, make_product, make_space, make_user

pytestmark = pytest.mark.django_db

URL = "/api/v1/metrics/"


def test_route_is_invisible_when_no_token_is_configured(settings):
    settings.METRICS_TOKEN = ""
    assert reverse("metrics") == URL
    response = APIClient().get(URL, HTTP_AUTHORIZATION="Bearer anything")
    assert response.status_code == 404


def test_wrong_or_missing_token_is_unauthorized(settings):
    settings.METRICS_TOKEN = "s3cret"
    client = APIClient()
    assert client.get(URL).status_code == 401
    response = client.get(URL, HTTP_AUTHORIZATION="Bearer nope")
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Bearer"


def test_exposition_lists_request_states_and_storage(settings):
    settings.METRICS_TOKEN = "s3cret"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    space = make_space("metrics-space")
    space.storage_bytes_used = 1234
    space.save(update_fields=["storage_bytes_used"])
    product = make_product(space, name="Metrics Widget")
    request = make_accepted_request(space, product, 1)
    HardwareRequest.objects.filter(pk=request.pk).update(
        status=HardwareRequest.Status.PENDING_APPROVAL
    )
    make_user("metrics-viewer")
    response = APIClient().get(URL, HTTP_X_METRICS_TOKEN="s3cret")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain; version=0.0.4")
    body = response.content.decode()
    assert "# TYPE spaceworks_hardware_requests gauge" in body
    assert 'spaceworks_hardware_requests{status="pending_approval"} 1' in body
    assert f'spaceworks_storage_bytes_used{{makerspace_id="{space.pk}"}} 1234' in body
    assert "spaceworks_storage_bytes_used_total 1234" in body
    assert "spaceworks_evidence_retention_last_expiry_timestamp_seconds 0" in body
    # Eager mode has no broker to read, so the queue gauge is declared but sample-less.
    assert "# TYPE spaceworks_celery_queue_length gauge" in body
    assert "spaceworks_celery_queue_length{" not in body
    assert product.name not in body  # no tenant content, only counts and ids


def test_metrics_view_is_documented_in_the_schema():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    operation = schema["paths"][URL]["get"]
    assert operation["tags"] == ["Health"]
    assert "200" in operation["responses"]
