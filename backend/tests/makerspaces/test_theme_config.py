import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.admin_api.serializers_makerspaces import MakerspaceSerializer
from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import bootstrap_payload
from apps.makerspaces.theme_validation import validate_theme_config


@pytest.mark.parametrize("theme", [
    None, [], "red", {"unknown": "#fff"}, {"mode": "auto"}, {"mode": False},
    {"primary_color": 12}, {"accent_color": "red"}, {"primary_color": "#ffff"},
    {"primary_color": "#ffffff\n"}, {"accent_color": "url(https://example.com)"},
    {"logo_url": "javascript:alert(1)"}, {"logo_url": "ftp://example.com/logo"},
    {"logo_url": "https://example.com/" + "x" * 2048},
])
def test_theme_config_rejects_invalid_shape_and_values(theme):
    with pytest.raises(ValidationError):
        validate_theme_config(theme)


@pytest.mark.parametrize("theme", [
    {}, {"mode": "system"}, {"mode": "light"}, {"mode": "dark"},
    {"primary_color": "#abc", "accent_color": "#AAbbCC", "logo_url": ""},
    {"primary_color": "", "logo_url": "https://example.com/logo.png"},
])
def test_theme_config_accepts_closed_partial_configuration(theme):
    assert validate_theme_config(theme) == theme


@pytest.mark.django_db
def test_theme_patch_is_validated_audited_and_shipped():
    api_client = APIClient()
    from apps.audit.models import AuditLog

    actor = User.objects.create_superuser(username="theme-root", password="strong-password")
    makerspace = Makerspace.objects.create(name="Theme Space", slug="theme-space")
    api_client.force_authenticate(actor)
    path = f"/api/v1/admin/makerspaces/{makerspace.pk}"
    before = makerspace.theme_config
    invalid = api_client.patch(path, {"theme_config": {"primary_color": "red"}}, format="json")
    assert invalid.status_code == 400
    assert "theme_config" in invalid.data
    makerspace.refresh_from_db()
    assert makerspace.theme_config == before
    theme = {"primary_color": "#f3c3dd", "accent_color": "#5a1633"}
    response = api_client.patch(path, {"theme_config": theme}, format="json")
    assert response.status_code == 200
    makerspace.refresh_from_db()
    assert makerspace.theme_config == theme
    assert bootstrap_payload(makerspace)["theme"]["primary_color"] == "#f3c3dd"
    assert AuditLog.objects.filter(makerspace=makerspace, actor=actor, action="makerspace.updated").exists()


def test_control_model_clean_rejects_invalid_theme():
    makerspace = Makerspace(name="Theme Space", slug="theme-space", theme_config={"accent_color": "red"})
    with pytest.raises(ValidationError) as caught:
        makerspace.clean()
    assert "theme_config" in caught.value.message_dict


@pytest.mark.parametrize("theme", [[], {"extra": "value"}, {"logo_url": "data:image/svg+xml,svg"}])
def test_api_serializer_exposes_theme_validation_errors(theme):
    serializer = MakerspaceSerializer(data={"theme_config": theme}, partial=True)
    assert not serializer.is_valid()
    assert "theme_config" in serializer.errors
