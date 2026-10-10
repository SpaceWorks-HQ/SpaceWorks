"""`/control/` makerspace edits go through the same transitions as the staff API.

The superadmin form wrote `frontend_domain` straight onto the row, so on managed hosting
a VERIFIED space whose domain was edited kept VERIFIED for a host nobody had verified --
and VERIFIED is the trust gate for CORS, staff sessions, Host validation and TLS. The
form also left general edits and creation unaudited.
"""

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.cors import staff_origin_is_registered
from apps.makerspaces.models import Makerspace
from tests.return_helpers import make_user

pytestmark = pytest.mark.django_db

MANAGED = ".space-works.tech"


def control_client():
    superadmin = make_user(
        "control-makerspace-super",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )
    # Managed hosting validates Host; `localhost` is an INFRA_HOSTS default.
    client = Client(HTTP_HOST="localhost")
    client.force_login(superadmin)
    return client


def form_payload(space, **changes):
    payload = {
        "name": space.name,
        "public_code": space.public_code,
        "slug": space.slug,
        "location": space.location,
        "default_loan_days": space.default_loan_days,
        "frontend_domain": space.frontend_domain or "",
        "capabilities": [f"module:{key}" for key in space.enabled_modules]
        + [f"feature:{key}" for key in space.enabled_features],
        "memberships-TOTAL_FORMS": "0",
        "memberships-INITIAL_FORMS": "0",
        "memberships-MIN_NUM_FORMS": "0",
        "memberships-MAX_NUM_FORMS": "1000",
        "_save": "Save",
    }
    if space.public_inventory_enabled:
        payload["public_inventory_enabled"] = "on"
    payload.update(changes)
    return payload


def save(client, space, **changes):
    return client.post(
        reverse("admin:makerspaces_makerspace_change", args=[space.pk]),
        form_payload(space, **changes),
    )


@override_settings(PLATFORM_DOMAIN_SUFFIX=MANAGED)
def test_managed_domain_edit_in_control_drops_verified_trust():
    space = Makerspace.objects.create(
        name="Control Managed",
        slug="control-managed",
        frontend_domain="old.example.org",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )
    assert staff_origin_is_registered("https://old.example.org")

    response = save(control_client(), space, frontend_domain="new.example.org")

    assert response.status_code == 302
    space.refresh_from_db()
    assert space.frontend_domain == "new.example.org"
    assert space.frontend_domain_status == Makerspace.DomainStatus.PENDING
    assert space.domain_verified_at is None
    assert space.frontend_domain_changed_at is not None
    assert not staff_origin_is_registered("https://new.example.org")
    assert not staff_origin_is_registered("https://old.example.org")
    entry = AuditLog.objects.get(action="makerspace.domain_changed", makerspace=space)
    assert entry.meta == {
        "before": "old.example.org",
        "after": "new.example.org",
        "status": Makerspace.DomainStatus.PENDING,
    }


@override_settings(PLATFORM_DOMAIN_SUFFIX="")
def test_self_host_domain_edit_in_control_is_trusted_at_once():
    space = Makerspace.objects.create(name="Control Self", slug="control-self")

    response = save(control_client(), space, frontend_domain="lab.example.org")

    assert response.status_code == 302
    space.refresh_from_db()
    assert space.frontend_domain_status == Makerspace.DomainStatus.VERIFIED
    assert space.domain_verified_at is not None
    assert AuditLog.objects.filter(action="makerspace.domain_changed", makerspace=space).exists()


@override_settings(PLATFORM_DOMAIN_SUFFIX=MANAGED)
def test_control_save_without_a_domain_change_keeps_verification():
    space = Makerspace.objects.create(
        name="Control Same",
        slug="control-same",
        frontend_domain="same.example.org",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )

    # Same host, different case: normalisation makes it no change at all.
    response = save(control_client(), space, frontend_domain="SAME.example.org", location="Hall B")

    assert response.status_code == 302
    space.refresh_from_db()
    assert space.frontend_domain_status == Makerspace.DomainStatus.VERIFIED
    assert not AuditLog.objects.filter(action="makerspace.domain_changed").exists()
    entry = AuditLog.objects.get(action="makerspace.updated", makerspace=space)
    assert entry.meta["via"] == "control"
    assert "location" in entry.meta["fields"]
    assert "Hall B" not in str(entry.meta)


def test_control_create_is_audited():
    client = control_client()
    response = client.post(
        reverse("admin:makerspaces_makerspace_add"),
        {
            "name": "Control New",
            "public_code": "CNEW",
            "slug": "control-new",
            "location": "",
            "default_loan_days": 7,
            "frontend_domain": "",
            "public_inventory_enabled": "on",
            "memberships-TOTAL_FORMS": "0",
            "memberships-INITIAL_FORMS": "0",
            "memberships-MIN_NUM_FORMS": "0",
            "memberships-MAX_NUM_FORMS": "1000",
            "_save": "Save",
        },
    )

    assert response.status_code == 302
    space = Makerspace.objects.get(slug="control-new")
    entry = AuditLog.objects.get(action="makerspace.created", makerspace=space)
    assert entry.meta == {"via": "control"}
