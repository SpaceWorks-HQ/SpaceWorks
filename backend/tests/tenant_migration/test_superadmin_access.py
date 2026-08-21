from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.tenant_migration.import_visibility import (
    scope_import_target_makerspaces,
)
from apps.tenant_migration.models import TenantImportJob


pytestmark = pytest.mark.django_db


def _superadmin(username):
    return User.objects.create_superuser(
        username=username,
        password="test-password",
        access_status=User.AccessStatus.ACTIVE,
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _space(slug, *, superadmin_access_enabled):
    return Makerspace.objects.create(
        name=slug.replace("-", " ").title(),
        slug=slug,
        superadmin_access_enabled=superadmin_access_enabled,
    )


def _closure_probe(monkeypatch):
    calls = []

    def compute(space):
        calls.append(space.pk)
        return {"digest": "a" * 64, "identities": []}

    monkeypatch.setattr(
        "apps.tenant_migration.views_admission_export.admission.compute_pending_closure",
        compute,
    )
    return calls


def test_hidden_makerspace_refuses_global_superadmin_before_disclosure_is_built(
    monkeypatch,
):
    actor = _superadmin("hidden-disclosure-root")
    space = _space("hidden-disclosure", superadmin_access_enabled=False)
    calls = _closure_probe(monkeypatch)

    response = _client(actor).get(
        reverse("tenant-migration-disclosure-closure", args=(space.pk,))
    )

    assert response.status_code == 403
    assert response.data == {
        "detail": "This makerspace turned off superadmin access.",
        "code": "permission_denied",
    }
    assert calls == []


def test_hidden_makerspace_allows_superadmin_with_manage_makerspace_membership(
    monkeypatch,
):
    actor = _superadmin("member-disclosure-root")
    space = _space("member-disclosure", superadmin_access_enabled=False)
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        status="active",
    )
    calls = _closure_probe(monkeypatch)

    response = _client(actor).get(
        reverse("tenant-migration-disclosure-closure", args=(space.pk,))
    )

    assert response.status_code == 200
    assert response.data == {"digest": "a" * 64, "identities": []}
    assert calls == [space.pk]


def test_enabled_makerspace_still_allows_global_superadmin(monkeypatch):
    actor = _superadmin("enabled-disclosure-root")
    space = _space("enabled-disclosure", superadmin_access_enabled=True)
    calls = _closure_probe(monkeypatch)

    response = _client(actor).get(
        reverse("tenant-migration-disclosure-closure", args=(space.pk,))
    )

    assert response.status_code == 200
    assert response.data == {"digest": "a" * 64, "identities": []}
    assert calls == [space.pk]


def test_importing_target_is_listed_only_for_entitled_superadmin():
    entitled = _superadmin("import-list-member-root")
    unentitled = _superadmin("import-list-nonmember-root")
    space = _space("hidden-import-target", superadmin_access_enabled=False)
    space.lifecycle_state = Makerspace.LifecycleState.IMPORTING
    space.save(update_fields=("lifecycle_state",))
    MakerspaceMembership.objects.create(
        user=entitled,
        makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        status="active",
    )
    job = TenantImportJob.objects.create(
        source_archive_digest="b" * 64,
        target_makerspace=space,
        status=TenantImportJob.Status.COMPLETED,
        expires_at=timezone.now() + timedelta(days=1),
    )

    entitled_response = _client(entitled).get(reverse("tenant-migration-imports"))
    unentitled_response = _client(unentitled).get(
        reverse("tenant-migration-imports")
    )

    assert entitled_response.status_code == 200
    assert str(job.pk) in {row["id"] for row in entitled_response.data}
    assert unentitled_response.status_code == 200
    assert str(job.pk) not in {row["id"] for row in unentitled_response.data}


def test_hidden_import_target_stays_out_of_global_superadmin_list():
    actor = _superadmin("hidden-import-list-root")
    space = _space("hidden-active-import-target", superadmin_access_enabled=False)
    job = TenantImportJob.objects.create(
        source_archive_digest="c" * 64,
        target_makerspace=space,
        expires_at=timezone.now() + timedelta(days=1),
    )

    response = _client(actor).get(reverse("tenant-migration-imports"))

    assert response.status_code == 200
    assert str(job.pk) not in {row["id"] for row in response.data}


def test_import_target_scope_fails_closed_for_non_superadmin():
    actor = User.objects.create_user(username="import-list-space-manager")
    space = _space("member-import-target", superadmin_access_enabled=True)
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        status="active",
    )

    visible_spaces = scope_import_target_makerspaces(
        actor, Makerspace.objects.filter(pk=space.pk)
    )

    assert not visible_spaces.exists()
