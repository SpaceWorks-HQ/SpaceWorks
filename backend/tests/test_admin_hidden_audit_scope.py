"""Hidden-tenant refusal for archival and audit verification control surfaces."""

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.utils import timezone

from apps.accounts.models import User
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace
from config.admin_access import NESTED_MAKERSPACE_LOOKUPS

pytestmark = pytest.mark.django_db


def test_unarchive_rejects_hidden_makerspace():
    superadmin = get_user_model().objects.create_user(
        username="hidden-unarchive-superadmin",
        email="hidden-unarchive-superadmin@example.com",
        password="test-pass",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )
    hidden_space = Makerspace.objects.create(
        name="Hidden Unarchive",
        slug="hidden-unarchive",
        superadmin_access_enabled=False,
        archived_at=timezone.now(),
        archived_by=superadmin,
    )

    with pytest.raises(ValidationError, match="Cannot unarchive a hidden makerspace."):
        lifecycle.unarchive(hidden_space, superadmin)



def test_verification_run_and_event_admins_hide_disabled_makerspace_rows():
    from apps.audit.models import AuditVerificationRun, AuditVerificationRunEvent

    assert NESTED_MAKERSPACE_LOOKUPS["audit.auditverificationrunevent"] == "run__makerspace_id"
    hidden_space = Makerspace.objects.create(
        name="Hidden runs", slug="hidden-vrun-scope", superadmin_access_enabled=False,
    )
    visible_space = Makerspace.objects.create(name="Visible runs", slug="visible-vrun-scope")
    runs, events = {}, {}
    for space in (hidden_space, visible_space):
        run = AuditVerificationRun.objects.create(
            makerspace=space, snapshot_max_id=0, filter_fingerprint="f" * 64,
        )
        runs[space.slug] = run
        events[space.slug] = AuditVerificationRunEvent.objects.create(run=run, state="QUEUED")
    superadmin = get_user_model().objects.create_user(
        username="vrun-scope-superadmin", email="vrun-scope-superadmin@example.com",
        password="test-pass", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE,
        is_staff=True, is_superuser=True,
    )
    request = RequestFactory().get("/control/audit/auditverificationrun/")
    request.user = superadmin

    run_rows = admin.site._registry[AuditVerificationRun].get_queryset(request)
    event_rows = admin.site._registry[AuditVerificationRunEvent].get_queryset(request)

    assert runs["hidden-vrun-scope"] not in run_rows and runs["visible-vrun-scope"] in run_rows
    assert events["hidden-vrun-scope"] not in event_rows
    assert events["visible-vrun-scope"] in event_rows
    run_admin = admin.site._registry[AuditVerificationRun]
    assert not run_admin.has_add_permission(request)
    assert not run_admin.has_change_permission(request)
    assert not run_admin.has_delete_permission(request)
