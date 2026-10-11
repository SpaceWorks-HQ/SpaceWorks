import pytest

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.organizations.models import Organization, OrganizationMakerspace
from tests.organizations.test_org_console_access import client_for
from tests.organizations.test_org_authority import make_makerspace, make_organization, make_user

pytestmark = pytest.mark.django_db
BASE = "/api/v1/admin/organizations/"


def superadmin():
    return make_user("org-setup-super", role=User.Role.SUPERADMIN)


def test_create_is_superadmin_only_and_audited():
    payload = {"name": "Network", "slug": "network"}
    assert client_for(make_user("org-setup-member")).post(BASE, payload, format="json").status_code == 403
    actor = superadmin()
    response = client_for(actor).post(BASE, payload, format="json")
    assert response.status_code == 201, response.data
    row = Organization.objects.get(pk=response.data["id"])
    assert row.created_by == actor and not row.public_profile_enabled
    assert AuditLog.objects.filter(actor=actor, action="organization.created", target_id=str(row.pk)).exists()
    assert client_for(actor).post(BASE, payload, format="json").status_code == 400


def test_link_update_unlink_scope_and_audit():
    actor = superadmin()
    org = make_organization("org-setup-links")
    space = make_makerspace("org-setup-space")
    base = f"{BASE}{org.pk}/makerspaces/"
    client = client_for(actor)
    payload = {"makerspace_id": space.pk, "relationship": "affiliate"}
    assert client_for(make_user("org-setup-denied")).post(base, payload, format="json").status_code == 403
    assert client.post(base, payload, format="json").status_code == 200
    assert client.post(base, {**payload, "relationship": "manager"}, format="json").status_code == 200
    assert client.get(base).data["results"][0]["relationship"] == "manager"
    assert client.delete(f"{base}{space.pk}/").status_code == 204
    assert not OrganizationMakerspace.objects.filter(organization=org, makerspace=space).exists()
    assert set(AuditLog.objects.filter(actor=actor, makerspace=space).values_list("action", flat=True)) >= {
        "organization.link_created", "organization.link_updated", "organization.link_deleted",
    }


def test_hidden_space_refused_and_not_listed_without_changing_links():
    actor = superadmin()
    org = make_organization("org-setup-hidden")
    space = make_makerspace("org-setup-hidden-space", superadmin_access_enabled=False)
    base = f"{BASE}{org.pk}/makerspaces/"
    link = OrganizationMakerspace.objects.create(organization=org, makerspace=space, relationship="manager")
    client = client_for(actor)
    assert client.get(base).data["count"] == 0
    assert client.post(base, {"makerspace_id": space.pk, "relationship": "owner"}, format="json").status_code == 404
    assert client.delete(f"{base}{space.pk}/").status_code == 404
    link.refresh_from_db()
    assert link.relationship == "manager"


def test_second_owner_is_conflict_and_preserves_both_organizations():
    actor = superadmin()
    space = make_makerspace("org-setup-one-owner")
    first, second = make_organization("org-first-owner"), make_organization("org-second-owner")
    OrganizationMakerspace.objects.create(organization=first, makerspace=space, relationship="owner")
    response = client_for(actor).post(f"{BASE}{second.pk}/makerspaces/", {"makerspace_id": space.pk, "relationship": "owner"}, format="json")
    assert response.status_code == 409
    assert response.data["code"] == "organization_conflict"
    assert OrganizationMakerspace.objects.filter(makerspace=space).count() == 1


def test_inactive_organization_cannot_extend_reach_or_write_a_link_audit():
    actor = superadmin()
    org, space = make_organization("org-inactive"), make_makerspace("org-inactive-space")
    org.is_active = False
    org.save(update_fields=["is_active"])
    response = client_for(actor).post(f"{BASE}{org.pk}/makerspaces/", {
        "makerspace_id": space.pk, "relationship": "manager",
    }, format="json")
    assert response.status_code == 409, response.data
    assert not OrganizationMakerspace.objects.filter(organization=org).exists()
    assert not AuditLog.objects.filter(actor=actor, makerspace=space, action="organization.link_created").exists()


@pytest.mark.django_db(transaction=True)
def test_frozen_space_blocks_link_update_and_unlink_and_writes_no_audit():
    from tests.tenant_migration.source_gate_helpers import close_gate
    actor = superadmin()
    org, space = make_organization("org-frozen"), make_makerspace("org-frozen-space")
    link = OrganizationMakerspace.objects.create(organization=org, makerspace=space, relationship="affiliate")
    close_gate(space, actor)
    client = client_for(actor)
    base = f"{BASE}{org.pk}/makerspaces/"
    assert client.get(base).status_code == 200
    assert client.post(base, {"makerspace_id": space.pk, "relationship": "owner"}, format="json").status_code == 423
    assert client.delete(f"{base}{space.pk}/").status_code == 423
    link.refresh_from_db()
    assert link.relationship == "affiliate"
    assert not AuditLog.objects.filter(action__startswith="organization.link_").exists()
