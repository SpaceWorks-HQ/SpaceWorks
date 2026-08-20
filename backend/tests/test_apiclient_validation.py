import pytest
from django.contrib import messages as admin_messages
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from apps.apiclients.admin import ApiKeyRequestAdmin
from apps.apiclients.models import ApiClient, ApiKeyRequest
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def test_issue_rejects_missing_or_empty_allowed_origins():
    makerspace = make_space("client-validation-model")

    with pytest.raises(ValidationError) as missing:
        ApiClient.issue(label="Missing origins", makerspace=makerspace, scopes=["public:read"])
    with pytest.raises(ValidationError) as empty:
        ApiClient.issue(
            label="Empty origins",
            makerspace=makerspace,
            allowed_origins=[],
            scopes=["public:read"],
        )

    assert "allowed_origins" in missing.value.message_dict
    assert "allowed_origins" in empty.value.message_dict
    assert ApiClient.objects.count() == 0


def test_admin_api_create_rejects_missing_or_empty_allowed_origins():
    makerspace = make_space("client-validation-api")
    admin = make_member("client-validation-api-admin", makerspace)
    client = authenticated_client(admin)
    url = f"/api/v1/admin/makerspace/{makerspace.id}/api-clients"

    missing = client.post(
        url, {"label": "Missing origins", "scopes": ["public:read"]}, format="json"
    )
    empty = client.post(
        url,
        {"label": "Empty origins", "allowed_origins": [], "scopes": ["public:read"]},
        format="json",
    )

    assert missing.status_code == 400
    assert empty.status_code == 400
    assert ApiClient.objects.count() == 0

def test_admin_api_create_maps_model_validation_error_to_400(monkeypatch):
    makerspace = make_space("client-validation-api-model")
    admin = make_member("client-validation-api-model-admin", makerspace)
    client = authenticated_client(admin)
    url = f"/api/v1/admin/makerspace/{makerspace.id}/api-clients"

    def reject_issue(**_kwargs):
        raise ValidationError(
            {"allowed_origins": "At least one allowed origin is required."}
        )

    monkeypatch.setattr(ApiClient, "issue", reject_issue)

    response = client.post(
        url,
        {
            "label": "Rejected by model",
            "allowed_origins": ["https://valid.test"],
            "scopes": ["public:read"],
        },
        format="json",
    )

    assert response.status_code == 400
    assert "allowed_origins" in response.data
    assert ApiClient.objects.count() == 0


def test_control_approve_surfaces_validation_error_without_creating_client(monkeypatch):
    makerspace = make_space("client-validation-control")
    superadmin = make_user(
        "client-validation-control-super",
        is_staff=True,
        is_superuser=True,
    )
    api_key_request = ApiKeyRequest.objects.create(
        makerspace=makerspace,
        label="Originless server",
        allowed_origins=[],
    )
    model_admin = ApiKeyRequestAdmin(ApiKeyRequest, AdminSite())
    request = RequestFactory().post("/control/apiclients/apikeyrequest/")
    request.user = superadmin
    captured_messages = []

    def capture_message(_request, message, level=admin_messages.INFO, **_kwargs):
        captured_messages.append((message, level))

    monkeypatch.setattr(model_admin, "message_user", capture_message)

    model_admin.approve_and_issue(
        request,
        ApiKeyRequest.objects.filter(pk=api_key_request.pk),
    )

    api_key_request.refresh_from_db()
    assert api_key_request.status == ApiKeyRequest.Status.PENDING
    assert ApiClient.objects.count() == 0
    assert captured_messages
    assert captured_messages[0][1] == admin_messages.ERROR
    assert "allowed_origins" in str(captured_messages[0][0])


def test_valid_issue_still_returns_raw_secret_and_persists_client():
    makerspace = make_space("client-validation-valid")

    client, raw_secret = ApiClient.issue(
        label="Valid server",
        makerspace=makerspace,
        allowed_origins=["https://valid.example.com"],
        client_type="server",
        scopes=["reports:read"],
        rate_limit_tier="trusted",
    )

    assert client.pk
    assert raw_secret
    assert client.get_secret() == raw_secret
    assert client.allowed_origins == ["https://valid.example.com"]
    assert client.scopes == ["reports:read"]
    assert client.rate_limit_tier == "trusted"
