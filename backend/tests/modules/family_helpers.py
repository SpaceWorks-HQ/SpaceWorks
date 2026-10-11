"""Small setups with explicit modules; never rely on the everything test default."""

from apps.accounts.models import User
from apps.makerspaces.capabilities import default_enabled_features
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import core_module_keys
from rest_framework.test import APIClient


def family_space(slug, *modules, loans=False):
    features = set(default_enabled_features())
    if not loans:
        features.discard("loans.enabled")
    return Makerspace.objects.create(
        name=slug, slug=slug,
        enabled_modules=sorted(core_module_keys() | set(modules)),
        enabled_features=sorted(features),
    )


def account(username, *, staff=False):
    return User.objects.create_user(
        username=username, email=f"{username}@example.test", display_name=username,
        role=User.Role.SUPERADMIN if staff else User.Role.REQUESTER,
        is_superuser=staff, is_staff=staff, phone="1234567890", access_status=User.AccessStatus.ACTIVE,
    )


def client(user=None):
    result = APIClient()
    if user:
        result.force_authenticate(user)
    return result


def assert_family_bootstrap(space, family, *, loans=False):
    from apps.makerspaces.loan_visibility import LOAN_MODULES
    from apps.makerspaces.platform import bootstrap_payload

    payload = bootstrap_payload(space)
    assert family in payload["modules"]
    if loans:
        assert "loans.enabled" in payload["features"]
        assert "catalog" in payload["workflows"]
    else:
        assert not LOAN_MODULES & set(payload["modules"])
        assert "loans.enabled" not in payload["features"]
        assert "request_submit" not in payload["workflows"]
        assert "self_checkout" not in payload["workflows"]
