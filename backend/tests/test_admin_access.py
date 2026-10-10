from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.operations.models import StockTransfer
from tests.accounts.mfa_helpers import force_mfa_login

pytestmark = pytest.mark.django_db


def make_user(username, **kwargs):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@e.com",
        access_status=User.AccessStatus.ACTIVE,
        **kwargs,
    )


def test_non_superadmin_staff_is_denied_from_django_admin_index():
    user = make_user(
        "admin-denied-manager",
        role=User.Role.SPACE_MANAGER,
        is_staff=True,
    )
    client = Client()
    force_mfa_login(client, user)

    response = client.get("/control/")

    assert response.status_code == 403


def test_superadmin_is_allowed_to_django_admin_index():
    user = make_user(
        "admin-allowed-superadmin",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )
    client = Client()
    force_mfa_login(client, user)

    response = client.get("/control/")

    assert response.status_code == 200


def test_react_staff_admin_api_path_is_not_gated_by_django_admin_middleware():
    makerspace = Makerspace.objects.create(name="API Staff", slug="api-staff")
    user = make_user(
        "api-staff-manager",
        role=User.Role.SPACE_MANAGER,
        is_staff=True,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/admin/makerspaces")

    assert response.status_code == 200


def test_django_admin_login_csp_allows_unsafe_eval():
    client = Client()

    response = client.get("/control/login/", SERVER_NAME="localhost")

    assert response.status_code == 200
    csp = response["Content-Security-Policy"]
    script_src = next(
        section for section in csp.split(";") if section.strip().startswith("script-src")
    )
    assert "'unsafe-eval'" in script_src


def test_non_admin_docs_root_csp_does_not_allow_unsafe_eval():
    client = Client()

    response = client.get("/", SERVER_NAME="localhost")

    assert response.status_code == 200
    csp = response["Content-Security-Policy"]
    assert "'unsafe-eval'" not in csp


@pytest.mark.django_db(transaction=True)
def test_superadmin_can_delete_archived_makerspace_from_django_admin(monkeypatch):
    superadmin = make_user(
        "admin-delete-archived-superadmin",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )
    makerspace = Makerspace.objects.create(
        name="Admin Delete Archived",
        slug="admin-delete-archived",
    )
    StockTransfer.objects.create(
        makerspace=makerspace,
        created_by=superadmin,
        reason="Admin delete regression",
    )
    AuditLog.objects.create(
        actor=superadmin,
        action="admin.delete_regression",
        makerspace=makerspace,
    )
    archived = lifecycle.archive(makerspace, superadmin)
    monkeypatch.setattr(lifecycle, "_delete_storage_keys", lambda keys: None)

    client = Client()
    force_mfa_login(client, superadmin)
    url = reverse("admin:makerspaces_makerspace_delete", args=[archived.pk])

    confirm = client.get(url)

    assert confirm.status_code == 200
    assert "doesn&#x27;t have permission" not in confirm.content.decode()

    deleted = client.post(url, {"post": "yes"})

    assert deleted.status_code == 302
    assert not Makerspace.objects.filter(pk=archived.pk).exists()
