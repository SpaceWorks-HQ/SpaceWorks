"""Platform settings and updates require a real superadmin user, never a client key."""

import pytest
from rest_framework.test import APIClient

from apps.apiclients.models import ApiClient
from apps.apiclients.scope_registry import SCOPE_VOCABULARY
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("path,method", [
    ("/api/v1/admin/platform/email-settings", "get"),
    ("/api/v1/admin/platform/email-settings", "patch"),
    ("/api/v1/admin/platform/update-settings", "get"),
    ("/api/v1/admin/platform/update-settings/update-now", "post"),
])
def test_platform_routes_refuse_managers_members_and_anonymous(path, method):
    space = make_space("platform-permissions")
    manager = make_member("platform-manager", space)
    member = make_user("platform-member")
    for user in (manager, member):
        response = getattr(authenticated_client(user), method)(path, {}, format="json")
        assert response.status_code == 403
    response = getattr(APIClient(), method)(path, {}, format="json")
    assert response.status_code == 401


def test_a_client_key_does_not_establish_a_superadmin_actor():
    # Even a client holding every declared scope cannot act as a superadmin.
    client, secret = ApiClient.issue(
        label="platform-client", scopes=sorted(SCOPE_VOCABULARY), allowed_origins=["https://client.example"],
    )
    response = APIClient().get(
        "/api/v1/admin/platform/email-settings", HTTP_X_CLIENT_ID=client.client_id,
        HTTP_X_SIGNATURE=secret, HTTP_ORIGIN="https://client.example",
    )
    assert response.status_code in {401, 403}
